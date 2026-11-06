"""Zora's operation grammar (plan/2026-11-06e §4.2): a closed set of typed edits to one scene's plan, who may write
each, and the ADDRESS each one writes.

Ported from PromptMotion Nova Studio's `studio/ops.py` + `brief_ops.py` (an operation names exactly what it changes,
so a model's answer is the size of the edit, not of the plan) and changed for a Hiru scene:

* the document is the planner's stored plan (treatment → sequences → shots, staging, end state); the script's lines are
  bound to the shots by code and are never a writable field (Hiru rule: dialogue is verbatim);
* a shot is named `S03`, a sequence `A`, an arc beat by its number from 1, a staging mark by its block and person;
* script, translation, canon, waivers and DoP notes are a PERSON's (a staged card), never a model's;
* locks are a person's click, never a model's.

The vocabulary below is copied from the planner's contract on purpose (the groups stay independent, as the planners copy
each other's lists): `tests/zora/test_ops.py` checks the two never drift apart.

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import re
from typing import Any, Literal

# ── the planner's vocabulary (copied, checked equal by a test) ─────────────────────────────────────

SIZES: tuple[str, ...] = ("EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV")
LINKS: tuple[str, ...] = ("cut", "continuous", "match")
TAKES: tuple[int, ...] = (4, 6, 8)
ADDED_KINDS: tuple[str, ...] = (
    "baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold", "plant", "transition",
    "empty_frame", "implied_action", "move",
)
FACINGS: tuple[str, ...] = ("", "left", "right", "camera", "away")
FRAME_SIDES: tuple[str, ...] = ("", "left", "right", "centre")

# ── who writes ────────────────────────────────────────────────────────────────────────────────────

# `conductor` transcribes the person's own words; `author` is the one creative call of a turn (and its repair passes);
# `person` is a click in the interface or a staged card the person accepted; `translator` stages a translation.
By = Literal["conductor", "author", "repair", "person", "translator", "code"]
MODELS: frozenset[str] = frozenset({"conductor", "author", "repair"})
CREATIVE: frozenset[str] = frozenset({"author", "repair"})

# The fields `treatment.set` may write, and the ones of each list entry.
TREATMENT_FIELDS: tuple[str, ...] = ("logline", "approach", "geography", "key_image")
ARC_FIELDS: tuple[str, ...] = ("beat", "feeling")
COLOUR_FIELDS: tuple[str, ...] = ("palette", "light", "grade")
SEQUENCE_FIELDS: tuple[str, ...] = ("title", "purpose")
SHOT_FIELDS: tuple[str, ...] = ("size", "angle", "lens", "link", "why", "over")
SOUND_FIELDS: tuple[str, ...] = ("ambience", "effects", "music", "silence")
# The top-level parts of a shot's camera design (`ir`) a model may write whole; deeper paths are one dot down.
IR_FIELDS: tuple[str, ...] = ("setting", "cinematography", "lighting", "subjects", "beats", "audio", "first_frame")
MARK_FIELDS: tuple[str, ...] = ("zone", "facing", "frame_side", "holding")
END_PERSON_FIELDS: tuple[str, ...] = ("where", "facing", "holding", "look")
END_FIELDS: tuple[str, ...] = ("time", "light")

OPS: dict[str, tuple[str, frozenset[str]]] = {
    # level, who may use it
    "treatment.set": ("treatment", frozenset({"conductor", "author", "repair", "person"})),
    "arc.set": ("treatment", frozenset({"conductor", "author", "repair", "person"})),
    "arc.add": ("treatment", frozenset({"conductor", "author", "repair", "person"})),
    "arc.remove": ("treatment", frozenset({"conductor", "author", "repair", "person"})),
    "colour.set": ("treatment", frozenset({"conductor", "author", "repair", "person"})),
    "sequence.set": ("sequence", frozenset({"conductor", "author", "repair", "person"})),
    "sequence.bounds": ("sequence", frozenset({"conductor", "author", "repair", "person"})),
    "sequence.add": ("sequence", frozenset({"conductor", "author", "repair", "person"})),
    "sequence.remove": ("sequence", frozenset({"conductor", "author", "repair", "person"})),
    "set": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "retime": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "use": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "sound.set": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "ir.set": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "split": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "merge": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "insert": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "remove": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "move": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "regroup": ("shot", frozenset({"conductor", "author", "repair", "person"})),
    "mark.set": ("staging", frozenset({"author", "repair", "person"})),
    "mark.add": ("staging", frozenset({"author", "repair", "person"})),
    "mark.remove": ("staging", frozenset({"author", "repair", "person"})),
    "zone.add": ("staging", frozenset({"author", "repair", "person"})),
    "end.set": ("end", frozenset({"conductor", "person"})),
    # never applied by the kernel: a staged card the person accepts, carried out by the paths that own the script
    "block.set": ("script", frozenset({"person"})),
    "block.insert": ("script", frozenset({"person"})),
    "block.remove": ("script", frozenset({"person"})),
    "block.translate": ("translation", frozenset({"translator"})),
    "canon.add": ("marks", frozenset({"person"})),
    "canon.remove": ("marks", frozenset({"person"})),
    "check.waive": ("marks", frozenset({"person"})),
    "check.restore": ("marks", frozenset({"person"})),
    "dop_note.set": ("marks", frozenset({"person"})),
    "lock": ("locks", frozenset({"person"})),
    "unlock": ("locks", frozenset({"person"})),
}
# Levels the kernel never applies: it STAGES them (the old chat's card paths do the work, with the person's yes).
STAGED_LEVELS: frozenset[str] = frozenset({"script", "translation", "marks"})
# Operations that change which shots exist or where they sit.
STRUCTURAL: frozenset[str] = frozenset({"split", "merge", "insert", "remove", "move"})
REMOVALS: frozenset[str] = frozenset({"remove", "arc.remove", "sequence.remove", "mark.remove"})
# Field edits: what the person sets this way (the conductor writing their words, or a click) becomes LOCKED.
LOCKING: frozenset[str] = frozenset({"treatment.set", "colour.set", "sequence.set", "set", "retime", "use",
                                     "sound.set", "ir.set", "regroup", "mark.set", "end.set"})
MAX_OPS = 40  # a batch longer than this is a rewrite wearing an edit's clothes (Nova)
MAX_TEXT = 1500  # one field: a longer value is a model re-emitting a document


class OpError(ValueError):
    """An operation that cannot be applied, with the reason a person can read."""


def ops_for(by: str) -> tuple[str, ...]:
    return tuple(name for name, (_, who) in OPS.items() if by in who)


def infer_op(op: Any) -> Any:
    """A `set` written without its name (Nova finding 5): a field and a value on a shot is the set it plainly is."""
    if isinstance(op, dict) and not op.get("op") and "value" in op and op.get("field") and op.get("shot") is not None:
        return {**op, "op": "set"}
    return op


def normalize_op(op: Any) -> dict[str, Any]:
    if not isinstance(op, dict):
        raise OpError("an operation must be an object")
    name = str(op.get("op") or "").strip().lower()
    if name not in OPS:
        raise OpError(f"there is no operation {name!r}")
    return {**op, "op": name}


# ── addresses ─────────────────────────────────────────────────────────────────────────────────────

_SHOT = re.compile(r"^\s*s?0*(\d+)\s*$", re.IGNORECASE)


def code(n: int) -> str:
    """A shot as people and models read it: S01."""
    return f"S{n:02d}"


def shot_number(value: Any) -> int:
    """`3`, `"3"`, `"S03"` and `"s3"` all name shot 3."""
    if isinstance(value, bool):
        raise OpError(f"{value!r} is not a shot")
    if isinstance(value, int):
        return value
    m = _SHOT.match(str(value or ""))
    if not m:
        raise OpError(f"{value!r} is not a shot (shots are named S01, S02, ...)")
    return int(m.group(1))


def whole(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise OpError(f"{name} must be a whole number, got {value!r}") from None


def text(value: Any, name: str) -> str:
    if value is None:
        raise OpError(f"{name} needs a value")
    if isinstance(value, (list, dict)):
        raise OpError(f"{name} takes words, not a {type(value).__name__}")
    return str(value).strip()[:MAX_TEXT]


def path_of(op: dict[str, Any]) -> str:
    """The address an operation writes, in ONE namespace shared by locks, ownership and the no-op rule. Shot paths use
    the number the op names (the kernel turns them into handles); a structural op writes the whole shot."""
    name = str(op.get("op") or "")
    try:
        if name == "treatment.set":
            return f"treatment.{op.get('field')}"
        if name.startswith("arc."):
            return f"arc.{op.get('n') or op.get('after') or ''}".rstrip(".")
        if name == "colour.set":
            return f"colour.{op.get('sequence')}.{op.get('field')}"
        if name == "sequence.set":
            return f"sequence.{op.get('id')}.{op.get('field')}"
        if name in ("sequence.bounds", "sequence.add", "sequence.remove"):
            return f"sequence.{op.get('id')}"
        if name == "set":
            return f"{code(shot_number(op.get('shot')))}.{op.get('field')}"
        if name == "retime":
            return f"{code(shot_number(op.get('shot')))}.take_s"
        if name == "use":
            return f"{code(shot_number(op.get('shot')))}.use_s"
        if name == "sound.set":
            return f"{code(shot_number(op.get('shot')))}.sound.{op.get('field')}"
        if name == "ir.set":
            return f"{code(shot_number(op.get('shot')))}.ir.{op.get('path')}"
        if name == "regroup":
            return f"{code(shot_number(op.get('shot')))}.sequence"
        if name in ("split", "remove", "move"):
            return code(shot_number(op.get("shot")))
        if name == "merge":
            return "+".join(code(shot_number(n)) for n in op.get("shots") or [])
        if name == "insert":
            return f"after.{code(shot_number(op.get('after') or 0))}"
        if name.startswith("mark."):
            return f"staging.b{op.get('block')}.{op.get('who')}"
        if name == "zone.add":
            return "staging.zones"
        if name == "end.set":
            return f"end.{op['who']}.{op.get('field')}" if op.get("who") else f"end.{op.get('field')}"
        if name in ("lock", "unlock"):
            return str(op.get("path") or "")
    except OpError:
        return f"?{name}"
    return name


# ── the conductor's guard: did it WRITE craft, rather than transcribe the person's words? ───────────

# Free-text fields: a value here is someone's craft. Closed lists (size, link, take) are not.
CREATIVE_FIELDS: frozenset[str] = frozenset({
    *TREATMENT_FIELDS, *ARC_FIELDS, *COLOUR_FIELDS, *SEQUENCE_FIELDS, "why", "angle", "lens", "over",
    "ambience", "effects", "music", *IR_FIELDS, "what", "zone", "holding", "where", "look", "time", "light",
})
_PUNCT = ".,!?;:'\"“”‘’()"


def written_text(op: dict[str, Any]) -> str:
    """The words an op writes into a creative field ("" when it writes none)."""
    name = str(op.get("op") or "")
    if name == "insert":
        return str(op.get("what") or "")
    if name in ("ir.set",):
        value = op.get("value")
        return value if isinstance(value, str) else ""
    field = str(op.get("field") or "")
    if field in CREATIVE_FIELDS and isinstance(op.get("value"), str):
        return str(op["value"])
    return ""


def invented(op: dict[str, Any], message: str, current: str = "") -> bool:
    """Nova's `_invented` (W4 and its regression fix): a creative value of four or more words, most of which are neither
    in the person's message nor in the text it replaces. Quoting the person passes; trimming a clause from the text that
    is there passes; a line of craft the conductor composed does not (it is a task for the author)."""
    words = [w.strip(_PUNCT).lower() for w in written_text(op).split()]
    words = [w for w in words if w]
    if len(words) < 4:
        return False
    known = {w.strip(_PUNCT).lower() for w in f"{message} {current}".split()}
    return sum(1 for w in words if w in known) / len(words) < 0.6
