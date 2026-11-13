"""Arm L: Sable as a LIGHTWEIGHT SHOT EDITOR (the person, 2026-11-13), built from what the Zora lab proved.

    actions (Accept, Reject, Use, undo)        code, then a short reply
    a plain command (size, take, remove)        code reads it (Zora lab `quick`), no model to understand it
    anything else                               ONE gpt-5-mini minimal call understands it and, for a question, a craft
                                                request (handed to Zora), "not here" or "unclear", writes the reply too
    an edit                                     the row kernel, the planner-free checks, the risk rule: save or a card;
                                                then a short reply (gpt-5-mini minimal)

No author: a new clip's picture is left for Zora (reported, not repaired). Code runs the checks every turn and shows
them to the model, including a clip that performs a line while stored silent (`unvoiced`). Turn cap `TURN_CAP_USD`.
The Zora lab's tested parts are used as they are (`lab/zora_rows`: coverage, kernel, checks, risk, turn helpers).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ZORA = HERE.parent / "zora_rows"
if str(ZORA) not in sys.path:
    sys.path.insert(1, str(ZORA))

import agents  # noqa: E402  (lab/zora_rows)
import checks  # noqa: E402
import risk  # noqa: E402
from coverage import Coverage  # noqa: E402
from kernel import Kernel  # noqa: E402
from turn import ACTION, UNDO, Card, Thread, _action, _facts, _save, _undo, changes, guard, plain, quick  # noqa: E402

Row = dict[str, Any]
TURN_CAP_USD = 0.005
# prod run 1: the light call (minimal effort) caught 1 of 3 story conflicts; a focused check at low effort runs only on
# an edit that changes what a shot shows
# prod4: at minimal effort the light call doubted clear edits, ignored a prompt rule and sent junk ops: low from prod5
LIGHT_MODELS = {"light": ("gpt-5-mini", "low", 2500), "reply_small": ("gpt-5-mini", "minimal", 1500),
                "check": ("gpt-5-mini", "low", 2500)}
PICTURE_FIELDS = ("sees", "why")
SCENE_REF = re.compile(r"\bE(\d+)\s*S(\d+)\b", re.I)
SPOKEN = ("dialogue", "voiceover", "sung")


def prompt(name: str) -> str:
    return (HERE / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()


def light_schema() -> dict[str, Any]:
    props = {"lane": {"type": "string", "enum": ["answer", "edit", "zora", "cannot", "clarify"]},
             "confidence": {"type": "number"}, "ops": {"type": "array", "items": agents.op_schema()},
             "answer": {"type": "string"}}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def prod_schema() -> dict[str, Any]:
    """The production-aware answer: the lane, one lookup of another scene, the ops (conflicts are the story check's)."""
    props = {"lane": {"type": "string", "enum": ["answer", "lookup", "edit", "zora", "cannot", "clarify"]},
             "confidence": {"type": "number"}, "lookup": {"type": "string"},
             "ops": {"type": "array", "items": agents.op_schema()},
             "answer": {"type": "string"}}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


QUICK_MOVE = re.compile(r"(?:please\s+)?(?:move|put)\s+(s\d+)\s+(before|after)\s+(s\d+)", re.I)


def quick_move(message: str, cov: Coverage) -> Row | None:
    """ "Move S15 before S14" / "put S03 after S05", read by code (run 1: the model asked to clarify a move "before",
    which the `move` operation only says as "after")."""
    m = QUICK_MOVE.fullmatch(message.strip().rstrip(".!"))
    if not m or cov.at(m.group(1)) is None or cov.at(m.group(3)) is None:
        return None
    target = int(m.group(3).lstrip("sS"))
    after = f"S{target - 1:02d}" if m.group(2).lower() == "before" and target > 1 else (
        "start" if m.group(2).lower() == "before" else m.group(3).upper())
    if after == m.group(1).upper():  # already there
        return None
    return {"lane": "edit", "ops": [{"op": "move", "shot": m.group(1).upper(), "after": after}]}


ADD_SIZES = {"insert": "INSERT", "shot": "MS", "clip": "MS", "close-up": "CU", "close up": "CU", "closeup": "CU",
             "cu": "CU", "wide": "WIDE", "wide shot": "WIDE", "two-shot": "TWO", "two shot": "TWO", "mcu": "MCU",
             "ms": "MS", "medium shot": "MS", "reaction": "MCU", "reaction shot": "MCU"}
ADD_ROLES = {"INSERT": "insert", "TWO": "two_shot", "WIDE": "master"}
QUICK_ADD = re.compile(
    r"(?:please\s+)?add\s+(?:an?\s+|one\s+)?"
    r"(?:(\d+)\s*(?:-|\s)?\s*(?:s|secs?|seconds?)\s+)?"
    r"(insert|shot|clip|close[- ]?up|closeup|cu|wide(?: shot)?|two[- ]shot|mcu|ms|medium shot|reaction(?: shot)?)\s+"
    r"after\s+(s\d+)\s*,?\s+(?:of|showing|that shows|where)\s+(.+)", re.I)
QUICK_SHOW = re.compile(
    r"(?:please\s+)?(?:in\s+(s\d+)\s*,?\s*show|make\s+(s\d+)\s+show|(s\d+)\s+should\s+show)\s+(.+)", re.I)


def quick_add(message: str, cov: Coverage) -> Row | None:
    """ "Add a 4-second insert after S03 of Dilini's anatomy textbook" / "Add a shot after S06 of Sahan handing ..."
    read by code (prod4: the model doubted a clear insert, and sent junk ops on another). What the clip shows is the
    person's words after "of" / "showing"; the size from the word they used; the take 4 s unless they said 4, 6 or 8;
    the block it covers is the last block of the shot it follows; who is on screen are the cast names in their words.
    A sentence that does not match whole, or a shot that does not exist, is the model's."""
    m = QUICK_ADD.fullmatch(message.strip().rstrip(".!"))
    if not m:
        return None
    after = cov.at(m.group(3))
    if after is None:
        return None
    take = int(m.group(1)) if m.group(1) else 4
    if take not in (4, 6, 8):
        return None
    size = ADD_SIZES.get(m.group(2).lower(), "MS")
    what = m.group(4).strip()
    block = max(after.last - 1, after.first)
    names = sorted({n for n in cov.names.values() if n and re.search(rf"\b{re.escape(n)}\b", what)})
    return {"lane": "edit", "ops": [{"op": "insert", "after": m.group(3).upper(), "role": ADD_ROLES.get(size, "single"),
                                     "size": size, "take_s": take, "first_block": block, "last_block": block,
                                     "who": names, "what": what}]}


def quick_show(message: str, cov: Coverage) -> Row | None:
    """ "In S05, show Dilini wearing jeans and a t-shirt" / "make S05 show ..." / "S05 should show ..." read by code
    (prod4: the model refused it as "a character's look"). What the shot shows becomes the person's words; the story
    check then warns when it clashes with the canon or the story."""
    m = QUICK_SHOW.fullmatch(message.strip().rstrip(".!"))
    if not m:
        return None
    ref = m.group(1) or m.group(2) or m.group(3)
    if cov.at(ref) is None:
        return None
    return {"lane": "edit", "ops": [{"op": "set", "shot": ref.upper(), "field": "sees", "value": m.group(4).strip()}]}


def card_reply(rec: Row) -> str:
    """A waiting card's reply, written by code from the card itself (run 1: the model said "I removed S08" while
    nothing was saved). Always a proposal, never done. A conflict with the story leads, as a heads-up the person may
    override."""
    would = [plain(x) for x in rec.get("would", [])[:3]]
    risky = [r for r in rec["card"]["reasons"] if not r.startswith("may contradict")]
    head = ""
    if rec.get("conflicts"):
        head = " ".join(f"Heads-up: the story says {c['fact'].rstrip('.')} ({c['source']}), but "
                        f"{c['why'][:1].lower() + c['why'][1:].rstrip('.')}." for c in rec["conflicts"][:2])
        head += " It's your call. "
    elif risky:
        head = f"This one needs your OK first, because it {' and '.join(risky)}. "
    return (head + "If you accept: " + "; ".join(would) + ". Nothing is saved until you press Accept; Reject leaves "
            "the scene as it is.")


def check_schema() -> dict[str, Any]:
    conflict = {"type": "object", "additionalProperties": False, "required": ["fact", "source", "why"],
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}, "why": {"type": "string"}}}
    props = {"conflicts": {"type": "array", "items": conflict}}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def pictured(ops: list[Row]) -> list[str]:
    """What an edit would newly SHOW, in the person's words: only these go to the story check (a size, a take, a move
    or a removal shows nothing new)."""
    out = []
    for o in ops:
        if o.get("op") == "insert" and o.get("what"):
            out.append(f"a new {o.get('size') or ''} clip after {o.get('after')} showing: {o['what']}"
                       + (f" (on screen: {', '.join(o.get('who') or [])})" if o.get("who") else ""))
        elif o.get("op") == "set" and o.get("field") in PICTURE_FIELDS and o.get("value"):
            out.append(f"{o.get('shot')} now shows: {o['value']}")
    return out


def story_check(prod: Any, th: Thread, ops: list[Row], backend: Any, slot: str, rec: Row) -> list[Row]:
    """The focused story check: the production card (cached) and the change, nothing else."""
    change = pictured(ops)
    if not change or prod is None:
        return []
    user = (f"{prod.card()}\n\nOPEN SCENE: {getattr(th, 'open_label', '')} (where the change is made; the scenes "
            "above are in story order)\n\nCHANGE:\n" + "\n".join(f"- {c}" for c in change))
    try:
        text, _ = backend.ask("check", f"{slot}.check", prompt("check"), user, check_schema(),
                              budget=left(backend, rec) - 0.001)  # leave the reply its share
    except (agents.OverBudget, agents.CutOff):
        rec["reported"].append("The story check did not fit this turn; the change was not checked against the story.")
        return []
    rec["story_check"] = json.loads(text).get("conflicts") or []
    return rec["story_check"]


def keep_words(ops: list[Row], message: str, rec: Row) -> list[Row]:
    """The person's words stand (prod2: asked for an ENGINEERING letter, the model wrote a MEDICAL one, so the story
    check saw nothing to warn about; it also rewrote every shot's reason unasked). In code, with the Zora lab's test of
    words the person did not say: a new clip's subject becomes the person's own sentence, and any other unasked prose is
    dropped."""
    from turn import _invented

    kept = []
    for o in ops:
        if not _invented(o, message):
            kept.append(o)
        elif o.get("op") == "insert":
            rec.setdefault("guarded", []).append(f"the new clip's subject kept in your words (the model had: "
                                                 f"{o.get('what')})")
            kept.append({**o, "what": message.strip().rstrip(".")})
        elif o.get("op") == "set" and o.get("field") == "sees":  # prod3: "show Dilini in jeans" was rewritten
            rec.setdefault("guarded", []).append(f"what {o.get('shot')} shows kept in your words (the model had: "
                                                 f"{o.get('value')})")
            kept.append({**o, "value": message.strip().rstrip(".")})
        else:
            rec.setdefault("guarded", []).append(f"not applied, you did not ask for it: {o.get('op')} {o.get('shot')} "
                                                 f"{o.get('field')}")
    return kept


def merge_conflicts(*lists: list[Row]) -> list[Row]:
    out, seen = [], set()
    for c in (c for lst in lists for c in lst or []):
        key = (str(c.get("source", "")).lower(), str(c.get("fact", "")).lower()[:40])
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def unvoiced(cov: Coverage) -> list[str]:
    """A clip that performs a line but is stored without speech (the bug the person found, plan/2026-11-13 §3.7)."""
    out = []
    for ln in cov.lines.values():
        c = cov.clip(ln.by) if ln.by else None
        if c is not None and c.sound_mode not in SPOKEN:
            want = "dialogue" if ln.speaker in c.on_screen else "voiceover"
            out.append(f"{cov.code(c.h)} performs {ln.lid} ({ln.speaker}) but is stored {c.sound_mode}: it should be "
                       f"{want}")
    return out


def view(cov: Coverage, message: str) -> str:
    """The scene for the light call: every clip one line, the shots the message names in full, the sound modes, and
    what code's checks found."""
    named = {c.h for n in re.findall(r"\bS(\d+)\b", message, re.I) if (c := cov.at(n)) is not None}
    found = [f.sentence for f in checks.find(cov)] + unvoiced(cov)
    sound = ", ".join(f"{cov.code(c.h)} {c.sound_mode}" for c in cov.clips)
    return (f"{cov.render(only=named)}\n\nSOUND MODE OF EACH CLIP: {sound}\n\nCHECKS (code, on the scene as it is "
            "now):\n" + ("\n".join(f"- {x}" for x in found) if found else "- nothing found"))


def left(backend: Any, rec: Row) -> float:
    return TURN_CAP_USD - sum(c.get("dollars", 0) for c in backend.calls[rec["calls_from"]:])


def run_turn(th: Thread, message: str, backend: Any, slot: str, prod: Any = None) -> Row:
    rec: Row = {"message": message, "slot": slot, "lane": "", "calls_from": len(backend.calls), "saved": False,
                "done": [], "refused": [], "team_refused": [], "notes": [], "undelivered": [], "reported": [],
                "kernel_notes": [], "card": None, "proposals": [], "fact": "", "author": [], "reply": "",
                "before_s": th.cov.total_s()}
    m = ACTION.match(message.strip())
    if m:
        card = th.card
        _action(th, m, rec)
        if card is not None and m.group(1).lower() == "accept":  # the person overrode a conflict with the story
            rec["override"] = [r for r in card.reasons if r.startswith("may contradict")]
        _reply(th, message, backend, slot, rec)
    elif UNDO.match(message):
        _undo(th, UNDO.match(message).group(1).lower(), rec)
        _reply(th, message, backend, slot, rec)
    elif (answer := quick(message, th.cov) or quick_move(message, th.cov) or quick_add(message, th.cov)
           or quick_show(message, th.cov)) is not None:
        rec["lane"], rec["by_code"] = "edit", True
        # prod4: code reads the edit, the story check still judges what it shows (a size or a take shows nothing new)
        found = merge_conflicts(story_check(prod, th, answer["ops"], backend, slot, rec))
        _apply(th, answer["ops"], rec, conflicts=found)
        _reply(th, message, backend, slot, rec)
    else:
        _light(th, message, backend, slot, rec, prod)
    rec["after_s"] = th.cov.total_s()
    rec["revision"] = th.revision
    rec["calls"] = backend.calls[rec.pop("calls_from"):]
    rec["dollars"] = round(sum(c.get("dollars", 0) for c in rec["calls"]), 5)
    th.history.append(f"Director: {message}")
    th.history.append(f"Sable: {rec['reply']}")
    return rec


def _light(th: Thread, message: str, backend: Any, slot: str, rec: Row, prod: Any = None) -> None:
    talk = "\n".join(th.history[-6:]) or "(no earlier messages)"
    if prod is None:
        system, schema = prompt("light"), light_schema()
        user = f"CONVERSATION (recent):\n{talk}\n\n{view(th.cov, message)}\n\nLATEST MESSAGE FROM THE DIRECTOR:\n{message}"
    else:  # the production card first: the same bytes every message, so the provider caches it
        system, schema = prompt("light_prod"), prod_schema()
        open_label = getattr(th, "open_label", "")
        named = [f"E{a}S{b}" for a, b in SCENE_REF.findall(message) if f"E{a}S{b}".upper() != open_label.upper()]
        # prod run 1: asked about E1S3's shots, the model guessed ("3 shots") instead of looking; code reads a scene
        # the message names into the input itself (one, no extra call)
        extra = f"\n\nSCENE {named[0].upper()} (read for you, read-only):\n{prod.read_scene(named[0])}" if named else ""
        user = (f"{prod.card()}\n\nOPEN SCENE: {open_label}\n{view(th.cov, message)}{extra}\n\n"
                f"CONVERSATION (recent):\n{talk}\n\nLATEST MESSAGE FROM THE DIRECTOR:\n{message}")
    try:
        text, _ = backend.ask("light", f"{slot}.light", system, user, schema, budget=left(backend, rec))
        ans = json.loads(text)
        ref = str(ans.get("lookup") or "").strip()
        if prod is not None and (ans["lane"] == "lookup" or ref) and ref:  # ONE lookup, then answer
            rec["lookup"] = ref
            more = (f"{user}\n\nLOOKUP RESULT ({ref}):\n{prod.read_scene(ref)}\n\nAnswer now with what you have; no "
                    "further lookup.")
            text, _ = backend.ask("light", f"{slot}.light2", system, more, schema, budget=left(backend, rec))
            ans = json.loads(text)
            if ans["lane"] == "lookup":
                ans["lane"] = "answer"
    except (agents.OverBudget, agents.CutOff) as exc:
        rec["lane"], rec["reply"] = "clarify", f"Sorry, I couldn't read that one through ({exc}); try it shorter?"
        return
    ans["ops"] = [agents.clean_op(o) for o in ans.get("ops") or []]
    rec["light"] = ans
    lane = ans["lane"] if ans["confidence"] >= 0.5 or ans["lane"] != "edit" else "clarify"
    rec["lane"] = lane
    if lane == "clarify" and ans["lane"] == "edit":  # prod2: unsure, yet its answer said "Inserted…": code asks instead
        rec["reply"] = ("I want to get this one right before I change anything: which shot should it come after, and "
                        "what exactly should we see?")
        return
    if lane == "edit":
        ans["ops"] = keep_words(ans["ops"], message, rec)
    if lane == "edit" and ans["ops"]:
        # prod3: the main call's own conflicts were noise (it listed facts that MATCH the story); only the focused
        # story check decides
        found = merge_conflicts(story_check(prod, th, ans["ops"], backend, slot, rec))
        _apply(th, ans["ops"], rec, conflicts=found)
        _reply(th, message, backend, slot, rec)
        return
    if lane == "edit":  # prod3: nothing was applied, yet the model's answer said "I set S05…": code says so
        rec["reply"] = "Nothing changed: I couldn't turn that into a change to this scene. Could you say it another way?"
        return
    reply = ans.get("answer") or "Could you say that another way? I'm not sure which shot you mean."
    rec["reply"], rec["guard_cut"] = guard(reply, card=False, proposals=False)


def _apply(th: Thread, ops: list[Row], rec: Row, conflicts: list[Row] | None = None) -> None:
    before = th.cov
    work = before.copy()
    k = Kernel(work)
    res = k.apply(ops, by="conductor")
    rec["refused"] += [f"{x['op'].get('op')} {x['op'].get('shot') or ''}: {x['reason']}" for x in res.rejected]
    rec["kernel_notes"] += res.notes
    found = checks.new(before, work)
    for f in found:  # no author here: a new clip's picture is Zora's to draw, reported (not a problem to repair)
        if f.code == "picture_empty":
            rec["reported"].append(f.sentence.split(":")[0] + ": its picture still needs drawing (Zora can draw it).")
        elif f.fix == "report":
            rec["reported"].append(f.sentence)
    unfixed = [f for f in checks.repairable(found) if f.code != "picture_empty"]
    done = changes(before, work)
    why = risk.reasons(res.applied, before, work, unfixed)
    if conflicts and done:  # a clash with the story: a warning card the person may override (the person, 2026-11-13)
        rec["conflicts"] = conflicts
        why += [f"may contradict {c.get('source', 'the story')}: {c.get('fact', '')}" for c in conflicts]
    rec["applied"] = [{"by": a["by"], "text": a["text"]} for a in res.applied]
    if why and done:
        th.card = Card(ops=[{"op": a["op"], "by": a["by"]} for a in res.applied], made_on=before.fingerprint(),
                       reasons=why, lines=risk.consequences(before, work, done, rec["kernel_notes"], unfixed))
        rec["card"] = {"reasons": why, "lines": th.card.lines}
        rec["would"] = done
        return
    rec["done"] = done
    if done:
        _save(th, work)
        rec["saved"] = True


def _reply(th: Thread, message: str, backend: Any, slot: str, rec: Row) -> None:
    if rec.get("card"):  # a proposal: code says it exactly, no model ($0)
        rec["reply"] = card_reply(rec)
        return
    said =message if not message.startswith("[") else f"(they pressed {message.strip('[]')})"
    talk = "\n".join(th.history[-6:]) or "(none)"
    user = (f"<recent_chat>\n{talk}\n</recent_chat>\n<scene>\n{th.cov.render(only=set())}\n</scene>\n<message>\n{said}"
            "\n</message>\n<turn>\nWHAT HAPPENED THIS TURN (the truth; it outranks the conversation):\n"
            + "\n\n".join(_facts(th, rec)) + "\n</turn>")
    try:
        text, _ = backend.ask("reply_small", f"{slot}.reply", prompt("reply"), user, None, budget=left(backend, rec))
        rec["reply"], rec["guard_cut"] = guard(text.strip(), card=bool(rec.get("card")), proposals=False)
    except (agents.OverBudget, agents.CutOff):
        rec["reply"] = "; ".join(rec["done"][:3]) or (rec.get("status") or "Nothing changed.")
