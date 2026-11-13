"""What a person does in Zora's panel besides writing (plan/2026-11-13 §3.4, §3.5, §3.7): plain JSON in and out. The
change itself is code, never a model.

    accept  a card's operations replayed IN THE BATCHES THEY LANDED IN (lab run 1: one at a time shifted the numbers),
            checked and saved as a revision of kind `use`; refused when the rows changed since the card was made
    reject  nothing changes; the card says so and the conductor is told not to offer it again in this thread
    use     an option's operations, the same replay
    undo    the rows as they were before the last change (itself a revision, so redo is the undo of the undo)
    redo
    lock    a field a person set: no model may write it. Unlock lifts it. Not a revision, and no version moves

After a click that touched a card or the rows, Zora answers in the thread in a sentence or two (the reply agent, inside
the same $0.02 turn budget; in code when no model fits).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from contracts.coverage import checks
from contracts.coverage.ledger import changes, plain, where
from contracts.coverage.scene import CINE, IR_JSON, IR_TEXT, Coverage
from contracts.producer import PersonEdits
from contracts.zora.events import ZoraAction, ZoraActionResult
from hiru_ai.core import agents, llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings
from hiru_ai.systems.zora.zora_chat import budget as B
from hiru_ai.systems.zora.zora_chat import scene as world_of
from hiru_ai.systems.zora.zora_chat.store import NO_UNDO, Saver
from hiru_ai.systems.zora.zora_chat.turn import PERSONA, Rec, gate_event, guard, kernel_mod, ledger_event

_log = logging.getLogger(__name__)
Row = dict[str, Any]
ROLE = "Your role can comment on the shots but not change them."
LOCKABLE = ("take_s", "size", "link", "sound", "sound_mode", "why", "sees", *CINE, *IR_TEXT, *IR_JSON)


def _result(saver: Saver | None, ok: bool, text: str, **more: Any) -> ZoraActionResult:
    stack = saver.stack() if saver is not None else None
    return ZoraActionResult(ok=ok, text=text, can_undo=bool(stack and stack.can_undo()),
                            can_redo=bool(stack and stack.can_redo()), **more)


def act(req: ZoraAction, ctx: RunContext) -> ZoraActionResult:
    if not req.can_edit:
        return ZoraActionResult(ok=False, text=ROLE)
    ctx = replace(ctx, scene_id=req.scene_id)
    world = world_of.read(ctx, req.production_id, req.scene_id)
    if isinstance(world, str):
        return ZoraActionResult(ok=False, text=world)
    saver = Saver(ctx, world, actor_user_id=req.actor_user_id, kept=get_settings().zora.revisions_kept)
    if req.kind in ("lock", "unlock"):
        return _lock(req, ctx, world, saver)
    if req.kind in ("undo", "redo"):
        if saver.stack() is None:
            return _result(saver, False, NO_UNDO)
        before = world.cov.copy()
        done = saver.restore(req.kind)
        if not done.ok:
            return _result(saver, False, done.reason)
        from hiru_ai.systems.zora.zora_chat.turn import _rehandled

        rec = Rec(lane=req.kind, saved=True, revision=done.revision, done=_rehandled(before, world.cov))
        word = "Undone" if req.kind == "undo" else "Redone"
        return _result(saver, True, f"{word}.", revision=done.revision, ops=ledger_event(rec), gate=gate_event(rec))
    return _card_click(req, ctx, world, saver)


# ── Accept, Reject, Use this ──────────────────────────────────────────────────────────────────────────────────────


def _batches(ops: list[Row]) -> list[tuple[str, list[Row]]]:
    """The operations in the batches they landed in: numbers are read at each batch's start."""
    out: list[tuple[str, list[Row]]] = []
    for o in ops:
        by, op = str(o.get("by") or "author"), dict(o.get("op") or {})
        if out and out[-1][0] == by:
            out[-1][1].append(op)
        else:
            out.append((by, [op]))
    return out


def replay(cov: Coverage, ops: list[Row]) -> tuple[Coverage, list[str], list[str]]:
    """→ (the coverage after the ops, what was refused, what code did on its own)."""
    K = kernel_mod()
    work = cov.copy()
    k = K.Kernel(work)
    refused, notes = [], []
    for by, batch in _batches(ops):
        r = k.apply(batch, by=by)
        refused += [x["reason"] for x in r.rejected]
        notes += r.notes
    return work, refused, notes


def _card_click(req: ZoraAction, ctx: RunContext, world: world_of.World, saver: Saver) -> ZoraActionResult:
    director = ctx.need("director")
    message = director.message(req.message_id) if req.message_id else None
    blocks = list((message or {}).get("blocks") or [])
    block = dict(blocks[req.block]) if 0 <= req.block < len(blocks) else {}
    thread_id = req.thread_id or (message or {}).get("thread_id")
    if req.kind == "use":
        options = block.get("options") or [] if block.get("kind") == "options" else []
        if not options or not 0 <= req.option < len(options):
            return _result(saver, False, "That option is no longer available.")
        if block.get("chosen") is not None:
            return _result(saver, False, "An option on that card was already used.")
        option = options[req.option]
        ops, made_on, label = list(option.get("ops") or []), str(option.get("made_on") or ""), \
            f"Used: {option.get('label', 'the option')}"
    else:
        if block.get("kind") != "confirm":
            return _result(saver, False, "That card is no longer available.")
        if block.get("state"):
            return _result(saver, False, f"That card was already {block['state']}.")
        ops, made_on, label = list(block.get("ops") or []), str(block.get("made_on") or ""), \
            "Accepted" if req.kind == "accept" else "Rejected"
    rec = Rec(lane="action")
    if req.kind == "reject":
        blocks[req.block] = {**block, "state": "rejected"}
        director.set_blocks(req.message_id, blocks)
        rec.fact = ("THE PERSON PRESSED REJECT on the card (" + "; ".join(block.get("reasons") or []) + "): nothing "
                    "changed, and Zora will not offer it again in this thread.")
        reply = _say(ctx, world, req, rec, thread_id, "[Reject]")
        return _result(saver, True, "Rejected · nothing changed.", ops=ledger_event(rec), gate=gate_event(rec),
                       message=reply)
    if made_on != world.cov.fingerprint():
        rec.fact = (f"THE PERSON PRESSED {label.split(':')[0].upper()}, but the scene changed since the card was made, "
                    "so nothing was applied: they should ask again and Zora works from the scene as it is now.")
        _say(ctx, world, req, rec, thread_id, f"[{label.split(':')[0]}]")
        return _result(saver, False, "The shots changed since this card was made; ask me again.")
    before = world.cov.copy()
    work, refused, notes = replay(world.cov, ops)
    rec.refused, rec.kernel_notes = refused, notes
    done = changes(before, work)
    rec.reported = [f.sentence for f in checks.new(before, work) if f.fix == "report"]
    rec.problems = [f.sentence for f in checks.repairable(checks.new(before, work))]
    if not done:
        return _result(saver, False, "That no longer changes anything in the shots.")
    saved = saver.save(work, kind="use", message_id=str(req.message_id or ""))
    if not saved.ok:
        return _result(saver, False, saved.reason)
    rec.saved, rec.revision, rec.done = True, saved.revision, done
    rec.touched = sorted({where(x) for x in done} - {"Scene"})
    if req.kind == "use":
        blocks[req.block] = {**block, "chosen": req.option, "outcome": f"{label} · revision {saved.revision}"}
    else:
        blocks[req.block] = {**block, "state": "accepted", "revision": saved.revision}
    director.set_blocks(req.message_id, blocks)
    rec.fact = (f"THE PERSON PRESSED {label.split(':')[0].upper()}: the change is now saved (revision "
                f"{saved.revision}; they can undo it).")
    reply = _say(ctx, world, req, rec, thread_id, f"[{label.split(':')[0]}]")
    return _result(saver, True, f"{label} · revision {saved.revision}.", revision=saved.revision,
                   ops=ledger_event(rec), gate=gate_event(rec), message=reply)


def _facts(rec: Rec) -> list[str]:
    out = [rec.fact]
    if rec.done:
        out.append("WHAT CHANGED (the app also shows this list under your message):\n"
                   + "\n".join(f"- {plain(x)}" for x in rec.done))
    if rec.refused:
        out.append("COULD NOT BE DONE (say so honestly, with the reason):\n" + "\n".join(f"- {x}" for x in rec.refused))
    if rec.reported or rec.problems:
        out.append("HEADS-UP (reported, never trimmed):\n" + "\n".join(f"- {x}" for x in rec.reported + rec.problems))
    return out


def _plain(rec: Rec) -> str:
    if rec.done:
        done = "; ".join(plain(x) for x in rec.done[:3])
        return f"Done, it's in: {done}. You can undo it if it doesn't sit right."
    if "REJECT" in rec.fact:
        return "Fine, I've left it as it was."
    return "The shots changed since that card was made, so I didn't apply it. Ask me again and I'll work from them now."


def _say(ctx: RunContext, world: world_of.World, req: ZoraAction, rec: Rec, thread_id: Any, pressed: str) -> Row | None:
    """Zora's sentence or two after a click, stored in the thread (gpt-5-mini minimal; in code when no model fits)."""
    if thread_id is None:
        return None
    text = ""
    if llm.models_enabled():
        budget = B.Budget(get_settings().zora.turn_cap_usd)
        run_ctx = budget.watch(ctx)
        history = ctx.need("director").messages(thread_id, 6)
        transcript = [f"{'Director' if m.get('kind') == 'user' else 'Zora'}: {m.get('text') or _text(m)}"
                      for m in history]
        shown = {c.h for x in rec.done if (c := world.cov.at(re.sub(r'\D', '', where(x)) or 0)) is not None}
        inp = {"persona": PERSONA, "transcript": transcript, "scene": world.cov.render(only=shown),
               "message": f"(they pressed {pressed.strip('[]')})", "facts": _facts(rec)}
        try:
            agent = agents.build("zora_reply")
            system, user = agent.messages(inp)
            cap = budget.output_cap(agent.manifest.model, system, user, "reply")
            text = str(agent.run(inp, run_ctx, max_output=cap).text)
            text, _ = guard(text.strip(), card=False, proposals=False)
        except Exception as exc:
            _log.warning("zora's reply to a click failed; using the plain one (%s)", B.describe(exc))
            text = ""
    text = text.strip() or _plain(rec)
    message = {"id": str(uuid.uuid4()), "production_id": str(req.production_id), "thread_id": str(thread_id),
               "kind": "director", "persona_id": None, "speaker": "Zora", "tone": "lead", "text": "",
               "blocks": [{"kind": "text", "text": text},
                          {"kind": "changes", "ops": ledger_event(rec), "gate": gate_event(rec),
                           "revision": rec.revision, "suggestions": [], "lane": "action"}],
               "ops": [], "citations": []}
    try:
        ctx.need("director").add_message(message)
    except Exception:
        _log.warning("zora's reply to a click was not stored", exc_info=True)
        return None
    return message


def _text(m: Row) -> str:
    return " ".join(str(b.get("text") or "") for b in m.get("blocks") or [] if b.get("kind") == "text").strip()


# ── locks ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _lock(req: ZoraAction, ctx: RunContext, world: world_of.World, saver: Saver) -> ZoraActionResult:
    """`path` is "S03.size" (a shot and one of LOCKABLE). Writes `duration_locked` or `person_edits.zora_locks` on that
    row only: no revision, no version moves (a lock changes nothing Veo is told)."""
    m = re.fullmatch(r"\s*S?(\d+)\.(\w+)\s*", req.path, re.I)
    clip = world.cov.at(m.group(1)) if m else None
    key = m.group(2).lower() if m else ""
    if clip is None or key not in LOCKABLE:
        return _result(saver, False, f"There is no shot field {req.path!r} to {req.kind}.")
    row = dict(world.cov.rows[clip.row_id])
    if key == "take_s":
        row["duration_locked"] = req.kind == "lock"
    else:
        edits = PersonEdits.of(row)
        locks = set(edits.zora_locks)
        locks = locks | {key} if req.kind == "lock" else locks - {key}
        row["person_edits"] = {**(row.get("person_edits") or {}), **edits.dump(), "zora_locks": sorted(locks)}
        if not locks:
            row["person_edits"].pop("zora_locks", None)
    ctx.need("scenes").save_plan(world.scene_row["id"], [row], [], [], {"updated_at": datetime.now(UTC).isoformat()})
    verb = "Locked" if req.kind == "lock" else "Unlocked"
    return _result(saver, True, f"{verb}: {world.cov.code(clip.h)} {key}.")
