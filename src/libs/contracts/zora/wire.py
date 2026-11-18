"""The answer shapes Zora holds its conductor and its author to (strict JSON-schema mode: every key present, unused ones
null), and the conversion back to operations on the shot rows (plan/2026-11-13 §3.9; the lab's
`lab/zora_rows/agents.py`).

In strict mode a model cannot be given an open object, so an operation is one of a closed set of shapes (`anyOf`), one
per operation, each with only its own fields and its `field` from a closed list (findings 2026-11-17 C1: one flat shape
for every operation let a model put insert's `who`, `role`, `first_block` and the screen's "on screen" into `set`).
`to_op` drops the nulls. The operations are the row kernel's (`steps/coverage_kernel`).

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The coverage contract's lists, repeated: `contracts.zora` imports only itself (tests/zora/test_isolation.py), and
# tests/zora/test_wire_shapes.py holds these equal to `contracts.coverage.scene`.
SIZES: tuple[str, ...] = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")
TAKES: tuple[int, ...] = (4, 6, 8)
CINE: tuple[str, ...] = ("angle", "lens", "movement")
IR_TEXT: tuple[str, ...] = ("setting", "lighting", "audio")
IR_JSON: tuple[str, ...] = ("beats", "subjects", "first_frame")
SOUND_MODES: tuple[str, ...] = ("dialogue", "voiceover", "sung", "ambient", "music_only", "silent")
PRIORITIES: tuple[str, ...] = ("must", "should", "nice")

# `board`: the person asks about or for the scene board (the storyboard picture), findings 2026-11-17 C4/C5
Lane = Literal["chat", "clarify", "edit", "craft", "options", "board", "cannot"]
LANES: tuple[str, ...] = ("chat", "clarify", "edit", "craft", "options", "board", "cannot")
WRITING_LANES: frozenset[str] = frozenset({"edit", "craft", "options"})
OP_NAMES: tuple[str, ...] = ("set", "retime", "sound", "sound_mode", "role", "insert", "remove", "split", "merge",
                             "move", "line")
# `framing` is a shot's size: its own kind, so a task about feeling never changes a CU to an MCU unasked (findings
# 2026-11-17 C9). `camera` is angle, lens, movement and the join.
KINDS: tuple[str, ...] = ("picture", "camera", "framing", "timing", "sound", "light", "order")
SET_FIELDS: tuple[str, ...] = ("size", "link", "why", "sees", *CINE, *IR_TEXT, *IR_JSON)  # the kernel's `set`
CONDUCTOR_SET_FIELDS: tuple[str, ...] = ("size", "link", *CINE)  # what the person's own words name
SOUND_FIELDS: tuple[str, ...] = ("ambience", "effects", "music", "silence")
HANDS: tuple[str, ...] = ("left", "right")


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConductorTask(_Loose):
    writes: list[str] = []  # the kinds of change the author may make (KINDS)
    shots: list[int] = []  # shot numbers AS PRINTED, before the turn's ops; [] = the whole scene
    instruction: str = ""


class Cannot(_Loose):
    reason: str = ""
    route: str = ""


class HandChange(_Loose):
    """From block `from_block` on, `who` holds `thing` in the `hand` hand (the scene's state ledger, which every frame's
    hands sentence is written from: findings 2026-11-17 C7)."""

    who: str = ""
    thing: str = ""
    hand: str = ""
    from_block: int = 0


class ConductorAnswer(_Loose):
    lane: Lane = "clarify"
    confidence: float = 0.0
    ops: list[dict[str, Any]] = []
    tasks: list[ConductorTask] = []
    variants: int = 0
    cannot: Cannot | None = None
    memory: str = ""
    hands: list[HandChange] = []

    def does_nothing(self) -> bool:
        """A writing lane that carries neither an op nor a task nor a hand (options may be all tasks; it needs one)."""
        return self.lane in ("edit", "craft") and not self.ops and not self.tasks and not self.hands


class Variant(_Loose):
    label: str = ""
    ops: list[dict[str, Any]] = []


class AuthorAnswer(_Loose):
    notes: str = ""
    ops: list[dict[str, Any]] = []
    asks: list[str] = []
    variants: list[Variant] = Field(default_factory=list)


_S = {"type": ["string", "null"]}
_I = {"type": ["integer", "null"]}
# Every field any operation uses (a reader of old answers, the lab, tests); the schema itself is `op_schema`
OP_FIELDS: dict[str, Any] = {"op": None, "shot": _S, "field": _S, "value": _S, "take_s": _I, "role": _S, "priority": _S,
                             "after": _S, "first_block": _I, "last_block": _I,
                             "who": {"type": ["array", "null"], "items": {"type": "string"}}, "what": _S,
                             "at_block": _I, "to_shot": _S, "line": _S}


def _enum(values: tuple[Any, ...], kind: str = "string") -> dict[str, Any]:
    return {"type": kind, "enum": list(values)}


def _enum_or_null(values: tuple[Any, ...], kind: str = "string") -> dict[str, Any]:
    return {"type": [kind, "null"], "enum": [*values, None]}


def op_shapes(set_fields: tuple[str, ...] = SET_FIELDS) -> dict[str, dict[str, Any]]:
    """Each operation's own fields (every one required; a field that may be left out is nullable)."""
    shot = {"type": "string"}
    return {
        "set": {"shot": shot, "field": _enum(set_fields), "value": {"type": "string"}},
        "retime": {"shot": shot, "take_s": _enum(TAKES, "integer")},
        "sound": {"shot": shot, "field": _enum(SOUND_FIELDS), "value": {"type": "string"}},
        "sound_mode": {"shot": shot, "value": _enum(SOUND_MODES)},
        "role": {"shot": shot, "role": _S, "priority": _enum_or_null(PRIORITIES)},
        "insert": {"after": {"type": "string"}, "role": {"type": "string"}, "size": _enum(SIZES),
                   "take_s": _enum_or_null(TAKES, "integer"), "first_block": {"type": "integer"}, "last_block": _I,
                   "who": {"type": "array", "items": {"type": "string"}}, "what": _S},
        "remove": {"shot": shot},
        "split": {"shot": shot, "at_block": {"type": "integer"}},
        "merge": {"shot": shot, "to_shot": {"type": "string"}},
        "move": {"shot": shot, "after": {"type": "string"}},
        "line": {"line": {"type": "string"}, "to_shot": {"type": "string"}},
    }


def _obj(props: dict[str, Any], title: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props,
                           "required": list(props)}
    return {"title": title, **out} if title else out


def op_schema(set_fields: tuple[str, ...] = SET_FIELDS) -> dict[str, Any]:
    """One operation: exactly one of the shapes, told apart by `op`."""
    return {"anyOf": [_obj({"op": {"type": "string", "enum": [name]}, **props})
                      for name, props in op_shapes(set_fields).items()]}


def hands_schema() -> dict[str, Any]:
    return _obj({"who": {"type": "string"}, "thing": {"type": "string"}, "hand": _enum(HANDS),
                 "from_block": {"type": "integer"}})


def conductor_schema() -> dict[str, Any]:
    task = _obj({"writes": {"type": "array", "items": {"type": "string", "enum": list(KINDS)}},
                 "shots": {"type": "array", "items": {"type": "integer"}}, "instruction": {"type": "string"}})
    cannot = {"anyOf": [{"type": "null"}, _obj({"reason": {"type": "string"}, "route": {"type": "string"}})]}
    return _obj({"lane": {"type": "string", "enum": list(LANES)}, "confidence": {"type": "number"},
                 "ops": {"type": "array", "items": op_schema(CONDUCTOR_SET_FIELDS)},
                 "tasks": {"type": "array", "items": task}, "variants": {"type": "integer"}, "cannot": cannot,
                 "memory": {"type": "string"}, "hands": {"type": "array", "items": hands_schema()}},
                "zora_conductor")


def author_schema() -> dict[str, Any]:
    variant = _obj({"label": {"type": "string"}, "ops": {"type": "array", "items": op_schema()}})
    return _obj({"notes": {"type": "string"}, "ops": {"type": "array", "items": op_schema()},
                 "asks": {"type": "array", "items": {"type": "string"}},
                 "variants": {"type": "array", "items": variant}}, "zora_author")


def to_op(raw: dict[str, Any]) -> dict[str, Any]:
    """An answer object → an operation: nulls and empty lists out."""
    return {k: v for k, v in raw.items() if v is not None and v != []}
