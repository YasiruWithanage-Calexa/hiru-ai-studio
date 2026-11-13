"""The answer shapes Zora holds its conductor and its author to (strict JSON-schema mode: every key present, unused ones
null), and the conversion back to operations on the shot rows (plan/2026-11-13 §3.9; the lab's
`lab/zora_rows/agents.py`).

In strict mode a model cannot be given an open object, so an operation is one flat object with every field any
operation uses; `to_op` drops the nulls. The operations are the row kernel's (`steps/coverage_kernel`).

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Lane = Literal["chat", "clarify", "edit", "craft", "options", "cannot"]
LANES: tuple[str, ...] = ("chat", "clarify", "edit", "craft", "options", "cannot")
WRITING_LANES: frozenset[str] = frozenset({"edit", "craft", "options"})
OP_NAMES: tuple[str, ...] = ("set", "retime", "sound", "sound_mode", "role", "insert", "remove", "split", "merge",
                             "move", "line")
KINDS: tuple[str, ...] = ("picture", "camera", "timing", "sound", "light", "order")


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConductorTask(_Loose):
    writes: list[str] = []  # the kinds of change the author may make (KINDS)
    shots: list[int] = []  # shot numbers AS PRINTED, before the turn's ops; [] = the whole scene
    instruction: str = ""


class Cannot(_Loose):
    reason: str = ""
    route: str = ""


class ConductorAnswer(_Loose):
    lane: Lane = "clarify"
    confidence: float = 0.0
    ops: list[dict[str, Any]] = []
    tasks: list[ConductorTask] = []
    variants: int = 0
    cannot: Cannot | None = None
    memory: str = ""

    def does_nothing(self) -> bool:
        """A writing lane that carries neither an op nor a task (options may be all tasks; it needs one)."""
        return self.lane in ("edit", "craft") and not self.ops and not self.tasks


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
_A = {"type": ["array", "null"], "items": {"type": "string"}}
OP_FIELDS: dict[str, Any] = {"op": None, "shot": _S, "field": _S, "value": _S, "take_s": _I, "role": _S, "priority": _S,
                             "after": _S, "first_block": _I, "last_block": _I, "who": _A, "what": _S, "at_block": _I,
                             "to_shot": _S, "line": _S}


def _obj(props: dict[str, Any], title: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props,
                           "required": list(props)}
    return {"title": title, **out} if title else out


def op_schema() -> dict[str, Any]:
    return _obj({k: ({"type": "string", "enum": list(OP_NAMES)} if v is None else v) for k, v in OP_FIELDS.items()})


def conductor_schema() -> dict[str, Any]:
    task = _obj({"writes": {"type": "array", "items": {"type": "string", "enum": list(KINDS)}},
                 "shots": {"type": "array", "items": {"type": "integer"}}, "instruction": {"type": "string"}})
    cannot = {"anyOf": [{"type": "null"}, _obj({"reason": {"type": "string"}, "route": {"type": "string"}})]}
    return _obj({"lane": {"type": "string", "enum": list(LANES)}, "confidence": {"type": "number"},
                 "ops": {"type": "array", "items": op_schema()}, "tasks": {"type": "array", "items": task},
                 "variants": {"type": "integer"}, "cannot": cannot, "memory": {"type": "string"}}, "zora_conductor")


def author_schema() -> dict[str, Any]:
    variant = _obj({"label": {"type": "string"}, "ops": {"type": "array", "items": op_schema()}})
    return _obj({"notes": {"type": "string"}, "ops": {"type": "array", "items": op_schema()},
                 "asks": {"type": "array", "items": {"type": "string"}},
                 "variants": {"type": "array", "items": variant}}, "zora_author")


def to_op(raw: dict[str, Any]) -> dict[str, Any]:
    """A flat answer object → an operation: nulls and empty lists out."""
    return {k: v for k, v in raw.items() if v is not None and v != []}
