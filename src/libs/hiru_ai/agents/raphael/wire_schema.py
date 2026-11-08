"""The strict JSON schemas Raphael's tools are held to, and the tool specs the model is given (plan/2026-11-08e §3.2,
§3.5).

Both agents (`raphael_planner`, `raphael_cinematic`) take their tool list from here. A tool's arguments are a wire class
of `contracts.raphael.wire`; a clip's camera design `ir` is a plain `dict` there because its shape is the clip schema
YAML the `serialize` step ships. OpenAI's strict mode refuses an open object, so each schema is the wire class's schema
with that design written into every `ir`.

The specs are in the Chat Completions function shape (`{"type": "function", "function": {...}}`) that
`BaseChatModel.bind_tools` takes; the lab's were the Responses API's flat shape with the same names, descriptions and
schemas.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from contracts.raphael.wire import SCHEMA_EDIT, SCHEMA_EXTRAS, SCHEMA_PUT, EditPlanW, ExtrasW, PutW
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
    """One clip's camera design: the clip schema's own fields (setting, cinematography, lighting, subjects, beats,
    audio,
    first_frame), the same ones the DoP fills."""
    clip = get_schema()
    props = {k: v for k, v in clip.shot_schema()["properties"].items() if k in clip.required_structure}
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _plain(node: Any) -> Any:
    """The schema without the class docstrings pydantic turns into `description` (a field NAMED description has an
    object as
    its value, so only a string value is dropped): the model is held to the lab's schema and is not sent prose twice."""
    if isinstance(node, dict):
        return {
            k: (v if k == "ir" else _plain(v))  # a clip's design is the clip schema's own, descriptions and all
            for k, v in node.items()
            if not (k == "description" and isinstance(v, str))
        }
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


def design_schema(wire: type[BaseModel], name: str) -> dict[str, Any]:
    """`wire`'s strict JSON schema, flat, with the clip schema's camera design as the type of every `ir`."""
    raw = wire.model_json_schema()
    flat = _plain(inline(raw, raw.get("$defs") or {}))
    design = ir_schema()

    def put(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: put(v) for k, v in node.items()}
            props = out.get("properties")
            if isinstance(props, dict) and "ir" in props:
                out["properties"] = {**props, "ir": design}
            return out
        if isinstance(node, list):
            return [put(v) for v in node]
        return node

    return {**put(flat), "title": name}


def _params(schema: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in schema.items() if k != "title"}


def _obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _spec(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters, "strict": True},
    }


_IDS = {"type": "array", "items": {"type": "string"}}
_TEXTS = {"type": "array", "items": {"type": "string"}}


def stage1_specs() -> list[dict[str, Any]]:
    return [
        _spec(
            "write_edit_plan",
            "Write the intended cut: treatment, sequences, moments (every script block in exactly one moment). "
            "Call it again to replace it. Write it first. Returns the check report.",
            _params(design_schema(EditPlanW, SCHEMA_EDIT)),
        ),
        _spec(
            "put_clips",
            "Add or replace clips, any number in one call, each COMPLETE: its plan and its Veo design (ir, sound). "
            'id "" adds a new clip (code gives the id and slate); the id of a clip in the bin replaces it (it keeps '
            "its id and slate, and a must clip stays must). Send a sequence at a time, and every repair the report "
            "asks for in one call. Returns the check report of the whole bin.",
            _params(design_schema(PutW, SCHEMA_PUT)),
        ),
        _spec(
            "remove_clips",
            "Take clips out of the bin. REFUSED for a clip whose removal would leave a block, a moment or a line "
            "without its must clip or its performer: replace it with put_clips instead. Returns the check report.",
            _obj(clip_ids=_IDS),
        ),
        _spec(
            "read_bin",
            "The clips in the bin, one row each (plan only, not the designs). moment 0 = every moment.",
            _obj(moment={"type": "integer"}),
        ),
        _spec(
            "finish",
            "Write the result: the intended cut, the shoot bin and your editor notes. REFUSES until no blocking "
            "fault remains. It is the last call.",
            _obj(editor_notes=_TEXTS),
        ),
    ]


def stage2_specs() -> list[dict[str, Any]]:
    review = {
        "type": "array",
        "items": _obj(moment={"type": "integer"}, earns={"type": "boolean"}, why={"type": "string"}),
    }
    return [
        _spec(
            "put_extras",
            "Add or replace cinematic clips, any number in one call, each COMPLETE: its plan, its Veo design (ir, "
            "sound), its anchor (the must clip id(s) it sits with) and its blend. "
            'id "" adds a new clip (code gives the id and slate); the id of one of YOUR cinematic clips replaces it. '
            "A must clip id is refused: the must clips are locked. Returns the check report of the whole bin.",
            _params(design_schema(ExtrasW, SCHEMA_EXTRAS)),
        ),
        _spec(
            "remove_extras",
            "Take cinematic clips out of the bin. A must clip id is refused. Returns the check report.",
            _obj(clip_ids=_IDS),
        ),
        _spec(
            "read_bin",
            "The clips in the bin, one row each (plan only, not the designs; must clips marked LOCKED). "
            "moment 0 = every moment.",
            _obj(moment={"type": "integer"}),
        ),
        _spec(
            "finish",
            "Write the result. blend_notes: for EACH cinematic clip, one note that starts with its id and says where "
            "it goes in the intended cut and over whose audio. moment_review: EVERY moment of the intended cut once: "
            "earns true when it has cinematic clips (why: what they give), false when it has none (why: why it needs "
            "none). REFUSES until no blocking fault remains and the review matches the bin. It is the last call.",
            _obj(blend_notes=_TEXTS, moment_review=review),
        ),
    ]
