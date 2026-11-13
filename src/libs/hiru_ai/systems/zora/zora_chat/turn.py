"""One Zora turn on the shot rows (plan/2026-11-13 §3.6; the lab's `lab/zora_rows/turn.py`, ported). The stages are
the nodes of the system's graph (`graph.py`):

    READ      the scene's rows as coverage, the thread
    IN CODE   "undo" / "redo" (a revision, no model)
    CONDUCT   quick(): a plain command code reads itself (no model); else the conductor (gpt-5-mini minimal): the lane,
              the person's explicit changes as OPERATIONS, TASKS with kinds and shots; one retry told what was wrong
    WORK      kernel → code's tasks → author (one call) → board → delivery → checks → repair (≤ 1) → risk:
              safe → saved in place; risky → a card with Accept / Reject, nothing saved
    REPLY     the facts as plain sentences, read last; streamed; the guard cuts what cannot stand; the message stored
              with its blocks (the changes, a card, options); a clip that performs a line but is stored silent is
              offered as a one-click card

Every model call is priced before it is sent and capped at what the turn can still afford (`budget.py`, $0.02).
Without a model key a plain command still works in code, and the reply is written in code.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import Any

from contracts.coverage import checks, risk
from contracts.coverage.ledger import changes, label, plain, short, where
from contracts.coverage.scene import CINE, IR_JSON, Coverage
from contracts.director import TurnPayload, without_replaced
from contracts.zora.wire import WRITING_LANES, ConductorAnswer, to_op
from hiru_ai.core import agents, llm, parts
from hiru_ai.core import memory as production_memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import ZoraSettings, get_settings
from hiru_ai.systems.zora.zora_chat import budget as B
from hiru_ai.systems.zora.zora_chat import scene as world_of
from hiru_ai.systems.zora.zora_chat.store import Saver

_log = logging.getLogger(__name__)
Row = dict[str, Any]
Event = tuple[str, Row]
Emit = Callable[[str, Row], None]
Ask = Callable[[str, Row, int], Row]  # (role, input, max output tokens) → the structured answer
Say = Callable[[Row, int], Iterator[str]]  # (input, max output tokens) → the reply, streamed
MIN_CONFIDENCE = 0.5
AGENT = {"conductor": "zora_conductor", "author": "zora_author", "reply": "zora_reply"}
PERSONA = ("You are Zora, the director's creative partner: a seasoned Sri Lankan TV drama director who loves this "
           "scene and talks to the team like a colleague on set.")
NO_MODEL = ("I can't work on that right now: my model is not available. Plain changes (\"Make S01 a wide\", \"Drop "
            "S08\"), undo and redo still work.")
ROLE_REFUSAL = "Your role can comment on the shots but not change them; a director, producer or writer can."
KIND_OF = {**{f: "camera" for f in ("size", "link", *CINE)}, **{f: "picture" for f in ("why", "sees", *IR_JSON)},
           "setting": "light", "lighting": "light", "audio": "sound"}
UNDO = re.compile(r"^\s*(undo|go back|redo)\b", re.I)


def kernel_mod() -> Any:
    """The row kernel, reached by id (ADR 0009)."""
    return parts.step("coverage_kernel", "logic")


# ── quick(): a plain command code reads itself (lab run 4: "a small request under $0.001") ──────────────────────────

SIZE_WORDS = {"wide": "WIDE", "wide shot": "WIDE", "ws": "WIDE", "medium": "MS", "medium shot": "MS", "ms": "MS",
              "mcu": "MCU", "medium close-up": "MCU", "medium close up": "MCU", "close-up": "CU", "close up": "CU",
              "closeup": "CU", "cu": "CU", "two-shot": "TWO", "two shot": "TWO", "ots": "OTS", "insert": "INSERT",
              "over the shoulder": "OTS", "over-the-shoulder": "OTS"}
QUICK_REMOVE = re.compile(r"(?:please\s+)?(?:drop|remove|delete|cut)\s+(s\d+)(?:\s*,.*)?", re.I)
QUICK_SET = re.compile(r"(?:please\s+)?(?:make\s+)?(s\d+)\s+(?:a\s+|an\s+|to\s+|into\s+)?(.+)", re.I)
QUICK_FIX = re.compile(r"\bfix\b", re.I)
SOUND_WORDS = re.compile(r"\b(silent|silence|sound|unvoiced|voice|voiced|mute|muted)\b", re.I)


def _answer(ops: list[Row]) -> Row:
    return {"lane": "edit", "confidence": 1.0, "ops": ops, "tasks": [], "variants": 0, "cannot": None, "memory": "",
            "by_code": True}


def quick(message: str, cov: Coverage) -> Row | None:
    """A plain command code reads itself, with no model: remove a shot, set a shot's size and/or take ("Make S01 a
    wide, 6 seconds", "S04 to 8 seconds", "Drop S08"), or fix the sound of the clips that perform a line but are
    stored silent ("fix the silent shots", "S07 has a line but it's silent, fix it"). Anything else is None."""
    text = message.strip().rstrip(".!")
    if QUICK_FIX.search(text) and SOUND_WORDS.search(text):
        ops: list[Row]
        named = {f"S{int(n):02d}" for n in re.findall(r"\bS(\d+)\b", text, re.I)}
        ops = [{"op": "sound_mode", "shot": cov.code(c.h), "value": mode} for c, mode in checks.unvoiced(cov)
               if not named or cov.code(c.h) in named]
        return _answer(ops) if ops else None
    ops = []
    m = QUICK_REMOVE.fullmatch(text)
    if m and cov.at(m.group(1)):
        ops = [{"op": "remove", "shot": m.group(1).upper()}]
    m = None if ops else QUICK_SET.fullmatch(text)
    if m and cov.at(m.group(1)):
        for part in re.split(r"\s*(?:,|\band\b)\s*", m.group(2)):
            p = re.sub(r"^(a|an)\s+", "", part.strip().lower())
            t = re.fullmatch(r"(\d+)\s*(?:s|secs?|seconds?)(?:\s+long)?", p)
            if t and int(t.group(1)) in (4, 6, 8):
                ops.append({"op": "retime", "shot": m.group(1).upper(), "take_s": int(t.group(1))})
            elif p in SIZE_WORDS:
                ops.append({"op": "set", "shot": m.group(1).upper(), "field": "size", "value": SIZE_WORDS[p]})
            else:
                return None
    return _answer(ops) if ops else None


def invented(op: Row, message: str) -> bool:
    """Prose the conductor wrote that the person did not say (most of its words are not in the message)."""
    prose = kernel_mod().PROSE
    if op.get("op") not in ("set", "insert") or (op.get("op") == "set" and op.get("field") not in prose):
        return False
    said = set(re.findall(r"\w+", message.lower()))
    words = re.findall(r"\w+", str(op.get("value") or op.get("what") or "").lower())
    return len(words) > 4 and len([w for w in words if w not in said]) > len(words) // 3


# ── the reply's guard (lab runs 2-4) ─────────────────────────────────────────────────────────────────────────────

# "the script card" is a route, not a card under the message, so only Zora's own cards and buttons count
CARD_WORDS = re.compile(r"\b(accept|reject|use this)\b|(?<!script )\b(the|a|on the) cards?\b", re.I)
LEAK = re.compile(r"(?i:what happened this turn)|WHAT CHANGED \(|WAITING FOR THEIR OK:|NOTHING CHANGED this turn|"
                  r"COULD NOT BE DONE|ASKED FOR BUT NOT DONE:|HEADS-UP \(|WHY THE TEAM DID IT|NOT POSSIBLE HERE:|"
                  r"THE PERSON (PRESSED|ASKED TO|PICKED)|THEY ASKED A QUESTION|OPTIONS shown as cards")


def guard(text: str, *, card: bool, proposals: bool) -> tuple[str, list[str]]:
    """Code takes out what cannot stand: the fact sheet pasted back, a card or a button that is not there."""
    cut: list[str] = []
    m = LEAK.search(text)
    if m and m.start() > 0:
        cut.append(text[m.start():])
        text = text[: m.start()].strip()
    if card or proposals:
        return text, cut
    kept: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+", text):
        (cut if CARD_WORDS.search(s) else kept).append(s)
    return " ".join(kept).strip() or text, cut


# ── what a turn did ──────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Rec:
    lane: str = ""
    fact: str = ""
    saved: bool = False
    revision: int = 0
    done: list[str] = field(default_factory=list)
    would: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    team_refused: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    undelivered: list[str] = field(default_factory=list)
    reported: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    kernel_notes: list[str] = field(default_factory=list)
    card: Row | None = None
    silent: Row | None = None  # the one-click sound fix offered this turn (§3.7)
    proposals: list[Row] = field(default_factory=list)  # every variant tried (the dropped ones say why)
    shown: list[Row] = field(default_factory=list)  # the ones offered
    author: list[Row] = field(default_factory=list)
    tasks: list[Row] = field(default_factory=list)
    applied: list[Row] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    repair: Row | None = None
    over_budget: bool = False
    memory: str = ""
    conductor: Row | None = None


def ledger_event(rec: Rec) -> Row:
    """The `ops` event and the `changes` block's ledger, in the shape the panel reads (one line per change)."""
    lines = []
    for x in rec.done:
        at = where(x)
        text = x[len(at) + 3:] if x.startswith(f"{at} · ") else x
        lines.append({"level": "shot", "where": at, "text": text, "by": ""})
    return {"changes": lines, "refused": [*rec.refused, *rec.team_refused], "undelivered": list(rec.undelivered),
            "nothing_changed": not rec.done, "staged": [], "mended": list(rec.kernel_notes),
            "stale": list(rec.touched)}


def gate_event(rec: Rec) -> Row:
    over = [x for x in rec.reported if "never trimmed" in x]
    return {"problems": [*rec.problems, *[x for x in rec.reported if x not in over]], "overruns": over, "seams": [],
            "already": []}


def plain_reply(rec: Rec) -> str:
    """The reply in code, when no model reply fits the turn: what happened, in one sentence."""
    if rec.fact and rec.lane in ("undo", "redo", "nomodel", "role", "cannot"):
        return rec.fact.split(" Every clip is generated")[0]
    if rec.card:
        return "This one needs your OK first: " + "; ".join(rec.card["reasons"]) + "."
    if rec.done:
        return "Done: " + "; ".join(plain(x) for x in rec.done[:3]) + "."
    if rec.shown:
        return "Here are " + str(len(rec.shown)) + " ways to do it: " + "; ".join(p["label"] for p in rec.shown) + "."
    if rec.lane == "clarify":
        return "I'm not sure what you'd like me to change. Could you say which shots, and what you want them to do?"
    return "Nothing changed this time."


# ── the turn ─────────────────────────────────────────────────────────────────────────────────────────────────────


class Turn:
    def __init__(self, req: TurnPayload, ctx: RunContext, emit: Emit, settings: ZoraSettings | None = None, *,
                 ask: Ask | None = None, say: Say | None = None) -> None:
        self.req, self.emit = req, emit
        self.cfg = settings or get_settings().zora
        self.budget = B.Budget(self.cfg.turn_cap_usd)
        self.ctx = self.budget.watch(dc_replace(ctx, scene_id=req.scene_id))
        self.rec = Rec()
        self.enabled = llm.models_enabled() or ask is not None
        self.ask: Ask = ask or self._ask
        self.say: Say = say or self._say
        self.answer: Row = {}

    # ── models, through the budget ────────────────────────────────────────────────────────────────────────────────

    def cap(self, role: str, inp: Row, *, reserve: float = 0.0) -> int:
        """The output tokens this call may spend (raises `OverBudget`)."""
        agent = agents.build(AGENT[role])
        system, user = agent.messages(inp)
        return self.budget.output_cap(agent.manifest.model, system, user, role, reserve=reserve)

    def _ask(self, role: str, inp: Row, max_out: int) -> Row:
        try:
            out = agents.build(AGENT[role]).run(inp, self.ctx, max_output=max_out)
        except Exception as exc:
            if B.cut_off(exc):
                raise B.CutOff(f"{role} was cut off at {max_out} output tokens") from exc
            raise
        return dict(out.model_dump(mode="json"))

    def _say(self, inp: Row, max_out: int) -> Iterator[str]:
        return agents.build(AGENT["reply"]).stream(inp, self.ctx, max_output=max_out)

    def call(self, role: str, inp: Row, *, reserve: float = 0.0) -> Row:
        return self.ask(role, inp, self.cap(role, inp, reserve=reserve))

    # ── read ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def read(self) -> bool:
        """→ False when there is nothing to edit (an error event was sent)."""
        req = self.req
        self.emit("status", {"text": "Reading the shots"})
        world = world_of.read(self.ctx, req.production_id, req.scene_id)
        if isinstance(world, str):
            self.emit("error", {"message": world})
            return False
        self.world = world
        self.before = world.cov.copy()
        self.director = self.ctx.need("director")
        self.saver = Saver(self.ctx, world, actor_user_id=req.actor_user_id, kept=self.cfg.revisions_kept)
        history = without_replaced([m for m in self.director.messages(req.thread_id, 12)
                                    if str(m.get("id")) != str(req.user_message_id)], req.replaces)
        self.history = history
        self.transcript = [f"{'Director' if m.get('kind') == 'user' else 'Zora'}: "
                           f"{m.get('text') or _blocks_text(m)}" for m in history]
        self.rejected = [r for m in history for b in m.get("blocks") or []
                         if b.get("kind") == "confirm" and b.get("state") == "rejected" for r in b.get("reasons") or []]
        return True

    # ── in code: undo, redo ───────────────────────────────────────────────────────────────────────────────────────

    def in_code(self) -> str:
        m = UNDO.match(self.req.message)
        return ("redo" if m.group(1).lower() == "redo" else "undo") if m else ""

    def restore(self) -> None:
        rec = self.rec
        rec.lane = rec.lane or "undo"
        if not self.req.can_edit:
            rec.fact, rec.lane = ROLE_REFUSAL, "role"
            return
        self.emit("status", {"text": "Undoing the last change" if rec.lane == "undo" else "Redoing it"})
        before = self.world.cov.copy()
        done = self.saver.restore(rec.lane)
        if not done.ok:
            rec.fact = done.reason
            return
        rec.saved, rec.revision = True, done.revision
        rec.done = _rehandled(before, self.world.cov)
        rec.touched = sorted({where(x) for x in rec.done} - {"Scene"})
        rec.fact = ("THE PERSON ASKED TO UNDO: the scene is back to how it was before the last change (saved as "
                    f"revision {done.revision}; they can redo)." if rec.lane == "undo" else
                    f"THE PERSON ASKED TO REDO: the change is back (revision {done.revision}).")
        self._plan_event()

    # ── conduct ───────────────────────────────────────────────────────────────────────────────────────────────────

    def conduct(self) -> str:
        """→ the lane. quick() first (no model); else the conductor, checked in code with one retry."""
        rec, cov = self.rec, self.world.cov
        answer = quick(self.req.message, cov)
        if answer is None and not self.enabled:
            rec.lane, rec.fact = "nomodel", NO_MODEL
            return "nomodel"
        if answer is None:
            answer = self._conduct()
        rec.conductor = answer
        if answer.get("memory"):
            self._remember(str(answer["memory"]).strip())
        lane = str(answer.get("lane") or "clarify")
        if float(answer.get("confidence") or 0) < MIN_CONFIDENCE and lane in WRITING_LANES:
            lane = "clarify"
        if lane in WRITING_LANES and not self.req.can_edit:
            rec.fact, lane = ROLE_REFUSAL, "role"
        self.answer = answer
        rec.lane = lane
        return lane

    def _conduct(self) -> Row:
        self.emit("status", {"text": "Reading your message"})
        cov, message = self.world.cov, self.req.message
        inp: Row = {"scene": cov.render(only=set()), "message": message, "transcript": self.transcript,
                    "rejected": self.rejected, "problems": [], "place": self.world.place(),
                    "people": self.world.people()}
        answer: Row | None = None
        problems: list[str] = []
        for _ in (1, 2):
            try:
                raw = self.call("conductor", {**inp, "problems": problems})
            except (B.OverBudget, B.CutOff) as exc:
                self.rec.team_refused.append(f"reading the message stopped at the turn's budget ({exc})")
                break
            except Exception:
                _log.warning("zora conductor failed", exc_info=True)
                break
            answer = ConductorAnswer.model_validate(raw).model_dump(mode="json")
            answer["ops"] = [to_op(o) for o in answer.get("ops") or []]
            problems = []
            if ConductorAnswer.model_validate(answer).does_nothing():
                problems.append(f"lane {answer['lane']} carries no operations and no tasks: give them, or choose the "
                                "lane that changes nothing")
            problems += [f"the {o.get('op')} on {o.get('shot') or 'the scene'} writes words the person did not say: "
                         "make it a task for the author" for o in answer["ops"] if invented(o, message)]
            if not problems:
                break
        if answer is None:  # no answer at all: the turn asks, it never guesses
            return {"lane": "clarify", "confidence": 0.0, "ops": [], "tasks": [], "variants": 0, "cannot": None,
                    "memory": ""}
        if problems:
            self.rec.team_refused += problems
            answer["ops"] = [o for o in answer["ops"] if not invented(o, message)]
        return answer

    def _remember(self, text: str) -> None:
        """A standing rule the person stated: a production memory entry the agents are given from then on."""
        if not self.req.can_edit or not text:
            return
        self.rec.memory = text
        item = {"id": str(uuid.uuid4()), "production_id": str(self.req.production_id),
                "scene_id": str(self.req.scene_id), "kind": "decision", "text": text[:2000],
                "source_ref": {"user_message_id": str(self.req.user_message_id), "by": "zora"},
                "created_by": str(self.req.actor_user_id)}
        try:
            from hiru_ai.rag.embeddings import embed_texts

            vectors = embed_texts([text], "zora.memory", self.ctx.sink()) if llm.models_enabled() else None
            self.director.add_memory(item, vectors[0] if vectors else None,
                                     get_settings().openai.embedding_model if vectors else "")
        except Exception:
            _log.warning("a rule to remember was not stored", exc_info=True)

    # ── lanes that write nothing ──────────────────────────────────────────────────────────────────────────────────

    def quiet(self) -> None:
        rec = self.rec
        if rec.lane == "cannot":
            c = self.answer.get("cannot") or {}
            rec.fact = (f"NOT POSSIBLE HERE: {c.get('reason', '')} Route: {c.get('route', '')} Every clip is generated "
                        "by Veo: never suggest ADR, a reshoot, a recorded take or an actor's new performance.")
        elif rec.lane == "clarify":
            rec.fact = ("THE REQUEST WAS NOT CLEAR: nothing was changed. Ask ONE short question that tells the "
                        "readings apart.")

    # ── the writing lanes ─────────────────────────────────────────────────────────────────────────────────────────

    def work(self) -> None:
        rec, answer = self.rec, self.answer
        K = kernel_mod()
        before = self.world.cov
        work = before.copy()
        k = K.Kernel(work)
        self.emit("status", {"text": "Applying your changes"})
        r0 = k.apply(list(answer.get("ops") or []), by="conductor")
        rec.refused += [f"{x['op'].get('op')} {x['op'].get('shot') or ''}: {x['reason']}" for x in r0.rejected]
        rec.kernel_notes += r0.notes
        applied = list(r0.applied)
        tasks = self._tasks(answer, work, before)
        rec.tasks = [{**t, "scope": [work.code(h) for h in t["scope"]]} for t in tasks]
        ans, variants = None, 0
        if tasks and not self.enabled:
            rec.team_refused.append("the craft work this needs could not be done: my model is not available")
            tasks = []
        if tasks:
            variants = max(2, min(int(answer.get("variants") or 2), self.cfg.variants_max)) if rec.lane == "options" \
                else 0
            try:  # the reply needs its share of the turn: the author may spend what is left after it
                ans = self._author(work, tasks, changes(before, work), variants, [])
            except (B.OverBudget, B.CutOff) as exc:
                rec.team_refused.append(f"the team's craft work did not fit this turn's budget ({exc})")
                rec.over_budget = True
            except Exception:
                _log.warning("zora author failed", exc_info=True)
                rec.team_refused.append("the craft work of this turn could not be done (the model did not answer)")
        if ans is not None:
            rec.author.append(ans)
            if ans.get("notes"):
                rec.notes.append(str(ans["notes"]))
            if variants:
                self._proposals(before, work, tasks, ans)
                return
            kept, refused = board(ans["ops"], tasks, work)
            rec.team_refused += refused
            r1 = k.apply(kept, by="author")
            applied += r1.applied
            rec.kernel_notes += r1.notes
            rec.team_refused += [f"the team's {x['op'].get('op')} {x['op'].get('shot') or ''}: {x['reason']}"
                                 for x in r1.rejected]
            now = changes(before, work)
            for t in tasks:  # delivery: a task about named shots that changed none of them was not done
                if t["scope"] and not t.get("code"):
                    hit = {h for h in t["scope"] if work.clip(h) is None
                           or any(line.startswith(work.code(h)) for line in now)}
                    if not hit:
                        rec.undelivered.append(t["instruction"])
        found = checks.new(before, work)
        fix = checks.repairable(found)
        if fix and self.enabled:
            snap = work.copy()
            allowed = sorted({w for t in tasks for w in t["writes"]}
                             | {"picture", "camera", "timing", "light", "sound"})
            rep_task = [{"writes": allowed, "scope": [], "instruction": "repair what the checks found"}]
            self.emit("status", {"text": "Fixing what the checks found"})
            try:
                rep = self._author(work, rep_task, changes(before, work), 0, [f.sentence for f in fix])
            except Exception as exc:
                rep = None
                rec.repair = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in fix],
                              "skipped": B.describe(exc)}
            if rep is not None:
                rec.author.append(rep)
                r2 = K.Kernel(work).apply([to_op(o) for o in rep.get("ops") or []], by="repair")
                again = checks.repairable(checks.new(before, work))
                if len(again) < len(fix):
                    applied += r2.applied
                    rec.repair = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in again]}
                else:
                    work.__dict__.update(snap.__dict__)
                    rec.repair = {"faults": [f.sentence for f in fix], "left": [f.sentence for f in fix],
                                  "dropped": True}
            found = checks.new(before, work)
        unfixed = checks.repairable(found)
        rec.reported = [f.sentence for f in found if f.fix == "report"]
        rec.problems = [f.sentence for f in unfixed]
        done = changes(before, work)
        why = risk.reasons(applied, before, work, unfixed)
        rec.applied = [{"by": a["by"], "text": a["text"]} for a in applied]
        if why and done:
            rec.card = {"kind": "confirm", "ops": [{"op": a["op"], "by": a["by"]} for a in applied],
                        "made_on": before.fingerprint(), "reasons": why,
                        "lines": risk.consequences(before, work, done, rec.kernel_notes, unfixed), "state": "",
                        "fix": ""}
            rec.would = done
            return
        if done:
            self._save(work, done)

    def _save(self, work: Coverage, done: list[str]) -> None:
        rec = self.rec
        self.emit("status", {"text": "Saving"})
        saved = self.saver.save(work, kind="turn", message_id="")
        if not saved.ok:
            rec.refused.append(saved.reason)
            return
        rec.saved, rec.revision, rec.done = True, saved.revision, done
        rec.touched = sorted({where(x) for x in done} - {"Scene"})
        self._plan_event()

    def _plan_event(self) -> None:
        rows = self.world.shot_rows
        self.emit("plan", {"shots": [_shot_view(r) for r in rows],
                           "total_s": sum(int(r.get("duration_s") or 0) for r in rows), "revision": self.rec.revision})

    def _tasks(self, answer: Row, work: Coverage, before: Coverage) -> list[Row]:
        out: list[Row] = []
        # lab run 5: on an insert the conductor still wrote a task for the new clip, aimed at the wrong shot
        asked = [] if any(o.get("op") == "insert" for o in answer.get("ops") or []) else answer.get("tasks") or []
        for t in asked:
            # numbers as printed, BEFORE this turn's ops (lab run 2); a clip the ops removed drops out
            hs = [c.h for n in t.get("shots") or [] if (c := before.at(n)) is not None and work.clip(c.h) is not None]
            out.append({"writes": list(t.get("writes") or []), "scope": hs,
                        "instruction": str(t.get("instruction") or "")})
        for c in work.clips:  # code's tasks, from what the ops provably did: a new or re-cut clip needs its picture
            if not c.why.strip() and not any(c.h in t["scope"] and "picture" in t["writes"] for t in out):
                if c.sees and "sees" in c.locks:
                    text = (f"write this new clip: why, camera, beats, subjects, first frame, sound, in the scene's "
                            f"continuity. The person asked for “{c.sees}” as a {c.size}: that is what we see and its "
                            "size (locked); build the picture on it")
                else:
                    text = ("write this new or re-cut clip whole: why, what we see, camera, beats, subjects, first "
                            "frame, sound, in the scene's continuity")
                out.append({"writes": ["picture", "camera", "light", "sound"], "scope": [c.h], "code": True,
                            "instruction": text})
        for ln in work.lines.values():  # a clip that now performs a line must show its speaker saying it
            c = work.clip(ln.by) if ln.by else None
            if c is None or ln.by == before.lines[ln.lid].by or not c.why.strip():
                continue
            if ln.speaker.lower() in c.sees.lower() and re.search(r"\b(say|says|speak|speaks|said|asks|tells)\b",
                                                                  c.sees, re.I):
                continue  # its picture already shows it (lab run 6: saves about $0.002 on "Drop S08")
            out.append({"writes": ["picture", "sound"], "scope": [c.h], "code": True,
                        "instruction": f"this clip now performs {ln.lid}: make its picture show {ln.speaker} saying it "
                                       "on camera (lips, beats, subjects, audio); keep its size and length"})
        # §3.7: the person asked for a silent clip's sound fix; its picture text may still say "no dialogue"
        for o in answer.get("ops") or []:
            if o.get("op") != "sound_mode":
                continue
            c = before.at(o.get("shot"))
            c2 = work.clip(c.h) if c is not None else None
            if c2 is None or not c2.ir or c2.sound_mode == c.sound_mode:  # type: ignore[union-attr]
                continue
            for ln in work.performs(c2.h):
                how = "heard off screen" if c2.sound_mode == "voiceover" else "said on camera"
                out.append({"writes": ["picture", "sound"], "scope": [c2.h], "code": True,
                            "instruction": f"it now carries {ln.speaker}'s line {ln.lid}, {how}: make its audio and "
                                           "beats say so; keep its size and length"})
        return out

    def _author(self, work: Coverage, tasks: list[Row], done: list[str], variants: int, faults: list[str]) -> Row:
        whole = any(not t["scope"] for t in tasks)
        only = None if whole else {h for t in tasks for h in t["scope"]}
        # a whole-scene task sees every clip by its head, reason and camera, no IR (lab run 5)
        scene = work.render(only=set(), brief=True) if whole else work.render(only=only)
        inp: Row = {"scene": scene, "transcript": self.transcript, "done": done, "variants": variants,
                    "faults": faults, "place": self.world.place(), "people": self.world.people(),
                    "tasks": [{"instruction": t["instruction"], "writes": t["writes"],
                               "on": ", ".join(work.code(h) for h in t["scope"]) or "any shot"} for t in tasks]}
        self.emit("status", {"text": "Working on the shots" if not faults else "Fixing what the checks found"})
        ans = self.call("author", inp, reserve=B.REPLY_RESERVE)
        ans["ops"] = [to_op(o) for o in ans.get("ops") or []]
        for v in ans.get("variants") or []:
            v["ops"] = [to_op(o) for o in v.get("ops") or []]
        return ans

    def _proposals(self, before: Coverage, work: Coverage, tasks: list[Row], ans: Row) -> None:
        K, rec = kernel_mod(), self.rec
        made_on = before.fingerprint()
        for v in (ans.get("variants") or [])[: self.cfg.variants_max]:
            trial = work.copy()
            kept, refused = board(v["ops"], tasks, trial)
            r = K.Kernel(trial).apply(kept, by="author")
            new = checks.repairable(checks.new(before, trial))
            lines = changes(before, trial)
            entry: Row = {"label": str(v.get("label") or "An option")[:120], "lines": lines,
                          "detail": "; ".join(plain(x) for x in lines[:4])[:400],
                          "change": f"{len(lines)} change{'s' if len(lines) != 1 else ''}",
                          "ops": [{"op": a["op"], "by": "author"} for a in r.applied],
                          "refused": refused + [x["reason"] for x in r.rejected],
                          "problems": [f.sentence for f in new],
                          "risky": risk.reasons(r.applied, before, trial, new), "made_on": made_on,
                          "intent": f"zora:{made_on}"}
            if not lines:
                entry["dropped"] = "changes nothing"
            elif new:
                entry["dropped"] = "fails the checks"
            rec.proposals.append(entry)
            if "dropped" not in entry:
                rec.shown.append(entry)

    # ── the silent-shot card (§3.7) ───────────────────────────────────────────────────────────────────────────────

    def offer_sound_fix(self) -> None:
        """A clip that performs a line but is stored silent is never fixed silently: the message carries a one-click
        card (Accept: code only), unless a card already waits this turn or the person was offered it already."""
        rec = self.rec
        if rec.card or rec.shown or not self.req.can_edit:
            return
        cov = self.world.cov
        found = checks.unvoiced(cov)
        offered = {str(o["op"].get("shot_id") or "") for m in self.history for b in m.get("blocks") or []
                   if b.get("kind") == "confirm" and b.get("fix") == "sound" and b.get("state") != "accepted"
                   for o in b.get("ops") or []}
        found = [(c, mode) for c, mode in found if c.row_id not in offered]
        if not found:
            return
        ops = [{"op": {"op": "sound_mode", "shot": cov.code(c.h), "value": mode, "shot_id": c.row_id}, "by": "code"}
               for c, mode in found]
        lines = []
        for c, mode in found:
            perf = cov.performs(c.h)
            who = ", ".join(f"{ln.speaker}'s line {ln.lid}" for ln in perf)
            how = "heard, not seen: voiced off screen" if mode == "voiceover" else "on camera: spoken"
            lines.append(f"Fix the sound on {cov.code(c.h)} ({who} is {how}; it is stored {c.sound_mode})")
        codes = ", ".join(cov.code(c.h) for c, _ in found)
        rec.silent = {"kind": "confirm", "ops": ops, "made_on": cov.fingerprint(),
                      "reasons": [f"{codes} perform{'s' if len(found) == 1 else ''} a line but "
                                  f"{'is' if len(found) == 1 else 'are'} stored without a voice"],
                      "lines": [*lines, "Only the sound mode changes; its prompt and video read as out of date "
                                        "(Regenerate when ready)."], "state": "", "fix": "sound"}

    # ── the reply ─────────────────────────────────────────────────────────────────────────────────────────────────

    def facts(self) -> list[str]:
        rec, nl = self.rec, "\n"
        out = [rec.fact] if rec.fact else []
        if rec.lane == "chat":
            out.append("THEY ASKED A QUESTION and nothing was changed. Answer it from the scene (the clips' why, "
                       "what we see, camera, sound), as the director who made these choices.")
        else:
            if rec.card:
                out.append("WAITING FOR THEIR OK: a card with Accept and Reject is under your message; nothing is "
                           "saved yet. It is asked because it " + "; ".join(rec.card["reasons"]) + ". If they accept:\n"
                           + nl.join(f"- {plain(x)}" for x in rec.would))
            elif rec.done:
                out.append("WHAT CHANGED (the app also shows this list under your message):\n"
                           + nl.join(f"- {plain(x)}" for x in rec.done))
            elif not rec.shown and rec.lane not in ("undo", "redo", "role", "nomodel"):
                out.append("NOTHING CHANGED this turn.")
            if rec.refused or rec.team_refused:
                out.append("COULD NOT BE DONE (say so honestly, with the reason):\n"
                           + nl.join(f"- {x}" for x in rec.refused + rec.team_refused))
            if rec.undelivered:
                out.append("ASKED FOR BUT NOT DONE:\n" + nl.join(f"- {x}" for x in rec.undelivered))
            if rec.reported or rec.problems:
                out.append("HEADS-UP (reported, never trimmed):\n"
                           + nl.join(f"- {x}" for x in rec.reported + rec.problems))
            if rec.lane == "options" and not rec.shown:
                why = "the team's work did not fit this turn" if rec.over_budget else "none of them passed the checks"
                out.append(f"NO OPTIONS ARE SHOWN ({why}). Say so plainly in one sentence and offer to try again on "
                           "fewer shots (for example only the last moment). Do not describe any option.")
            elif rec.shown:
                rows = [f"- {p['label']}" + (" (needs their OK: " + "; ".join(p["risky"]) + ")" if p["risky"] else "")
                        for p in rec.shown]
                out.append("OPTIONS shown as cards under your message, each with “Use this”:\n" + nl.join(rows))
            if rec.notes and not rec.team_refused and not rec.undelivered:
                out.append("WHY THE TEAM DID IT (their own words; use only where WHAT CHANGED backs it):\n"
                           + nl.join(f"- {n}" for n in rec.notes))
        if rec.silent:
            out.append("HEADS-UP: " + "; ".join(rec.silent["reasons"]) + ", so its video would be told nobody speaks. "
                       "A card under your message fixes the sound with one click (Accept); nothing is changed until "
                       "they press it.")
        return out

    def reply(self) -> None:
        rec = self.rec
        self.offer_sound_fix()
        ledger, gate = ledger_event(rec), gate_event(rec)
        self.emit("ops", ledger)
        self.emit("gate", gate)
        if rec.shown:
            self.emit("proposals", {"options": [_option(p) for p in rec.shown]})
        for card in (rec.card, rec.silent):
            if card:
                self.emit("confirm", _card(card))
        self.emit("status", {"text": "Writing the reply"})
        text = ""
        has_card = bool(rec.card or rec.silent)
        if self.enabled:
            try:
                inp = self._reply_input()
                chunks = self.say(inp, self.cap("reply", inp))
                for delta in chunks:
                    text += delta
                    self.emit("delta", {"text": delta})
                text, _ = guard(text.strip(), card=has_card, proposals=bool(rec.shown))
            except Exception as exc:
                _log.warning("zora reply failed or did not fit; using the plain reply (%s)", B.describe(exc))
                text = ""
        if not text.strip():
            text = plain_reply(rec)
            self.emit("delta", {"text": text})
        self._store(text.strip(), ledger, gate)

    def _reply_input(self) -> Row:
        rec, cov = self.rec, self.world.cov
        shown: set[str] = set()
        for line in rec.would + rec.done:
            m = re.match(r"(?:new |restored )?S(\d+)", line)
            if m and (c := (self.before if rec.would and line in rec.would else cov).at(m.group(1))):
                if cov.clip(c.h):
                    shown.add(c.h)
        for n in re.findall(r"\bS(\d+)\b", self.req.message, re.I):
            if c := cov.at(n):
                shown.add(c.h)
        big = bool(rec.author)
        return {"persona": PERSONA, "transcript": self.transcript[-(12 if big else 6):],
                "scene": cov.render(only=shown), "message": self.req.message, "facts": self.facts()}

    def _store(self, text: str, ledger: Row, gate: Row) -> None:
        rec, req = self.rec, self.req
        blocks: list[Row] = [{"kind": "text", "text": text},
                             {"kind": "changes", "ops": ledger, "gate": gate, "revision": rec.revision,
                              "suggestions": [], "lane": rec.lane}]
        for card in (rec.card, rec.silent):
            if card:
                blocks.append(_card(card))
        if rec.shown:
            blocks.append({"kind": "options", "question": "", "options": [_option(p) for p in rec.shown]})
        if used := production_memory.used_block(self.ctx):
            blocks.append(used)
        message = {"id": str(uuid.uuid4()), "production_id": str(req.production_id), "thread_id": str(req.thread_id),
                   "kind": "director", "persona_id": None, "speaker": "Zora", "tone": "lead", "text": "",
                   "blocks": blocks, "ops": [], "citations": []}
        self.director.add_message(message)
        self.emit("message", message)
        self.emit("done", {"message_id": message["id"], "lane": rec.lane, "revision": rec.revision, "suggestions": []})


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _kind(op: Row) -> str:
    name = op.get("op")
    if name == "set":
        return KIND_OF.get(str(op.get("field")), "picture")
    return {"retime": "timing", "sound": "sound", "sound_mode": "sound"}.get(str(name), "order")


def board(ops: list[Row], tasks: list[Row], work: Coverage) -> tuple[list[Row], list[str]]:
    """The author kept to its tasks: an operation of a kind no task allows, or on a shot outside its tasks, is
    refused."""
    kept, refused = [], []
    for o in ops:
        c = work.at(o.get("shot")) if o.get("shot") is not None else None
        k = _kind(o)
        if any(k in t["writes"] and (not t["scope"] or c is None or c.h in t["scope"]) for t in tasks):
            kept.append(o)
        else:
            on = f" on {o.get('shot')}" if o.get("shot") else ""
            refused.append(f"the team's {o.get('op')} {o.get('field') or ''}{on}: outside this turn's task ({k})")
    return kept, refused


def _card(card: Row) -> Row:
    """A card as stored in the message and sent to the panel."""
    return {"kind": "confirm", "ops": card["ops"], "made_on": card["made_on"], "reasons": list(card["reasons"]),
            "lines": list(card["lines"]), "state": card.get("state") or "", "fix": card.get("fix") or "",
            "revision": int(card.get("revision") or 0)}


def _option(p: Row) -> Row:
    risky = list(p.get("risky") or [])
    out = {"label": p["label"], "detail": p["detail"], "change": p["change"], "ops": p["ops"],
           "made_on": p["made_on"], "intent": p["intent"], "risky": risky, "needs_ok": bool(risky)}
    if risky:  # the card says so (its "Use this" is the person's OK)
        out["impact"] = "Needs your OK: it " + "; ".join(risky)
    return out


def _rehandled(before: Coverage, after: Coverage) -> list[str]:
    """What an undo or redo changed: the two coverages are read from rows, so their clips are matched by row id."""
    by_id = {c.row_id: c.h for c in before.clips}
    for c in after.clips:
        c.h = by_id.get(c.row_id) or f"r:{c.row_id}"
        c.new = False
    return changes(before, after)


def _shot_view(row: Row) -> Row:
    keys = ("id", "number", "title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end")
    return {k: row.get(k) for k in keys}


def _blocks_text(m: Row) -> str:
    return " ".join(str(b.get("text") or "") for b in m.get("blocks") or [] if b.get("kind") == "text").strip()


__all__ = ["Event", "Rec", "Turn", "board", "guard", "label", "ledger_event", "plain_reply", "quick", "short"]
