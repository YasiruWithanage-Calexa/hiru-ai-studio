"""The strict JSON schema Jonathan's agents are held to (plan/2026-11-05e §4.2).

`jonathan_author` and `jonathan_revise` both answer a whole `JonathanWire`, which carries shots, and a shot's camera
design `ir`
is a plain `dict` in the wire classes because its shape is the clip schema YAML the `serialize` step ships. OpenAI's
strict mode refuses an open object ("'additionalProperties' is required to be supplied and to be false"), so each
agent's `output_schema()` is its wire class's schema with that design written into every shot.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from hiru_ai.steps.serialize.schema import get_schema


def inline(node: Any, defs: dict[str, Any]) -> Any:
    """A JSON schema with every `$ref` replaced by the definition it names (strict mode wants one flat tree)."""
    if isinstance(node, dict):
        if "$ref" in node:
            return inline(defs[str(node["$ref"]).rsplit("/", 1)[-1]], defs)
        return {k: inline(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [inline(v, defs) for v in node]
    return node


def ir_schema() -> dict[str, Any]:
    """One shot's camera design: the clip schema's own fields (setting, cinematography, lighting, subjects, beats,
    audio, first_frame), the same ones the DoP fills."""
    clip = get_schema()
    props = {k: v for k, v in clip.shot_schema()["properties"].items() if k in clip.required_structure}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _with_design(node: Any, design: dict[str, Any]) -> Any:
    """`node` with the `ir` of every shot (the object that has both `ir` and `take_s`) replaced by `design`."""
    if isinstance(node, dict):
        out = {k: _with_design(v, design) for k, v in node.items()}
        props = out.get("properties")
        if isinstance(props, dict) and "ir" in props and "take_s" in props:
            out["properties"] = {**props, "ir": design}
        return out
    if isinstance(node, list):
        return [_with_design(v, design) for v in node]
    return node


def wire_schema(wire: type[BaseModel], name: str) -> dict[str, Any]:
    """`wire`'s JSON schema, flat, with the clip schema's camera design in every shot, titled `name`."""
    raw = wire.model_json_schema()
    schema = _with_design(inline(raw, raw.get("$defs") or {}), ir_schema())
    return {**schema, "title": name}
