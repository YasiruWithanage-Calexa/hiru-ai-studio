"""The answer shapes Zora holds its conductor and its author to (strict JSON-schema mode: every key present, unused
ones null), and the conversion back to Zora's operations (nulls dropped, a structured `ir.set` value parsed). Written
for the lab (plan/2026-11-06e Phase 3) and moved here for the agents (Phase 4), so the lab and the product send the same
bytes.

In strict mode a model cannot be given an open object, so an operation is one flat object with every field any
operation uses; code keeps the ones its op reads (`contracts.zora.ops`). `ConductorAnswer` and `AuthorAnswer` are what
the agents return after the wire: plain lists of raw objects, converted with `to_op` by the caller.

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.zora import ops as O

Lane = Literal["chat", "clarify", "edit", "craft", "shape", "options", "translate", "cannot"]
LANES: tuple[str, ...] = ("chat", "clarify", "edit", "craft", "shape", "options", "translate", "cannot")
# Lanes that may change nothing (W6): every other lane with no ops and no tasks is re-asked once.
QUIET_LANES: frozenset[str] = frozenset({"chat", "clarify", "options", "translate", "cannot"})


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ConductorTask(_Loose):
    writes: list[str] = []
    scope: list[int] = []  # shot numbers AFTER the turn's ops; [] = the whole scene
    instruction: str = ""
    may: list[str] = []  # further effects it may write (code's tasks; the conductor's wire has no such field)


class Cannot(_Loose):
    request: str = ""
    reason: str = ""
    route: str = ""


class Translate(_Loose):
    to: str = ""


class ConductorAnswer(_Loose):
    lane: Lane = "clarify"
    confidence: float = 0.0
    ops: list[dict[str, Any]] = []
    tasks: list[ConductorTask] = []
    variants: int = 0
    translate: Translate | None = None
    cannot: Cannot | None = None
    memory: str = ""

    def does_nothing(self) -> bool:
        """W6: a lane that should write and carries neither an op nor a task."""
        return self.lane not in QUIET_LANES and not self.ops and not self.tasks


class Variant(_Loose):
    label: str = ""
    ops: list[dict[str, Any]] = []


class AuthorAnswer(_Loose):
    notes: str = ""
    ops: list[dict[str, Any]] = []
    asks: list[str] = []
    variants: list[Variant] = Field(default_factory=list)

_STR = {"type": ["string", "null"]}
_INT = {"type": ["integer", "null"]}
_STRS = {"type": ["array", "null"], "items": {"type": "string"}}

OP_FIELDS: dict[str, Any] = {
    "op": None, "shot": _STR, "shots": _STRS, "field": _STR, "path": _STR, "value": _STR, "take_s": _INT, "use_s": _INT,
    "after": _STR, "kind": _STR, "what": _STR, "who": _STRS, "object": _STR, "at_block": _INT, "id": _STR,
    "first": _STR, "last": _STR, "n": _INT, "beat": _STR, "feeling": _STR, "sequence": _STR, "block": _INT,
    "zone": _STR, "facing": _STR, "frame_side": _STR, "holding": _STR, "title": _STR, "purpose": _STR,
}
_INTEGER_ADDRESS = {"first", "last", "after"}  # a shot (or a block, for arc ops) written as text: "S03" or "3"


def op_schema(names: tuple[str, ...]) -> dict[str, Any]:
    props = {k: ({"type": "string", "enum": sorted(names)} if k == "op" else v) for k, v in OP_FIELDS.items()}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def conductor_schema() -> dict[str, Any]:
    ops = sorted(set(O.ops_for("conductor")) - {n for n, (lvl, _) in O.OPS.items() if lvl in O.STAGED_LEVELS})
    task = {"type": "object", "additionalProperties": False,
            "properties": {"writes": {"type": "array", "items": {"type": "string"}},
                           "scope": {"type": "array", "items": {"type": "integer"}}, "instruction": {"type": "string"}},
            "required": ["writes", "scope", "instruction"]}
    cannot = {"type": ["object", "null"], "additionalProperties": False,
              "properties": {"request": {"type": "string"}, "reason": {"type": "string"}, "route": {"type": "string"}},
              "required": ["request", "reason", "route"]}
    translate = {"type": ["object", "null"], "additionalProperties": False,
                 "properties": {"to": {"type": "string"}}, "required": ["to"]}
    props = {"lane": {"type": "string", "enum": ["chat", "clarify", "edit", "craft", "shape", "options", "translate",
                                                  "cannot"]},
             "confidence": {"type": "number"}, "ops": {"type": "array", "items": op_schema(tuple(ops))},
             "tasks": {"type": "array", "items": task}, "variants": {"type": "integer"}, "translate": translate,
             "cannot": cannot, "memory": {"type": "string"}}
    return {"title": "zora_conductor", "type": "object", "additionalProperties": False, "properties": props,
            "required": list(props)}


def author_schema() -> dict[str, Any]:
    ops = op_schema(O.ops_for("author"))
    variant = {"type": "object", "additionalProperties": False,
               "properties": {"label": {"type": "string"}, "ops": {"type": "array", "items": ops}},
               "required": ["label", "ops"]}
    props = {"notes": {"type": "string"}, "ops": {"type": "array", "items": ops},
             "asks": {"type": "array", "items": {"type": "string"}}, "variants": {"type": "array", "items": variant}}
    return {"title": "zora_author", "type": "object", "additionalProperties": False, "properties": props,
            "required": list(props)}


def to_op(raw: dict[str, Any]) -> dict[str, Any]:
    """A flat answer object → a Zora operation: nulls and empty lists out, a structured `ir.set` value parsed."""
    op = {k: v for k, v in raw.items() if v is not None and v != []}
    name = str(op.get("op") or "")
    if name == "ir.set" and isinstance(op.get("value"), str) and op["value"].strip()[:1] in "{[":
        try:
            op["value"] = json.loads(op["value"])
        except ValueError:
            pass
    if name == "sound.set" and op.get("field") == "silence" and isinstance(op.get("value"), str):
        op["value"] = op["value"].strip().lower() in ("true", "yes", "1")
    for k in _INTEGER_ADDRESS:
        if isinstance(op.get(k), str) and name.startswith("arc.") and op[k].strip().lstrip("b").isdigit():
            op[k] = int(op[k].strip().lstrip("b"))
    return op
