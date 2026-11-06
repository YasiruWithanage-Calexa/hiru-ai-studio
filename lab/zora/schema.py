"""The answer shapes the lab holds the conductor and the author to (strict JSON-schema mode: every key present, unused
ones null), and the conversion back to Zora's operations (nulls dropped, a structured `ir.set` value parsed).

In strict mode a model cannot be given an open object, so an operation is one flat object with every field any
operation uses; code keeps the ones its op reads (`contracts.zora.ops`)."""
from __future__ import annotations

import json
from typing import Any

from contracts.zora import ops as O

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
