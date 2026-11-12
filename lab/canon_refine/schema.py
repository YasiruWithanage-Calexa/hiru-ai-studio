"""The refine call's answer: a strict JSON schema (every field required, nothing extra), and its pydantic twin for code.

Every fact is a Value: `script` with the line it was read from, or `inferred` with a one-line reason.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Value(_M):
    value: str
    source: Literal["script", "inferred"]
    line: int  # the document line a `script` value was read from; 0 when inferred
    reason: str  # why, for an inferred value; "" for script


class Person(_M):
    id: str
    gender: Value  # "man" | "woman"
    age: Value  # a number or a short range ("30", "late 20s")
    appearance: Value  # face, build, skin tone, hair: what a camera needs to cast and repeat them
    wardrobe: Value  # the base everyday wardrobe for who they are
    voice: Value  # timbre and manner


class Place(_M):
    id: str
    kind: Literal["set", "vehicle", "region", "spot", "unseen"]
    parent: str  # for a spot: the L id of the set or vehicle it is part of; else ""
    look: Value  # sets and vehicles: the place itself, with no people; others: "" or a short note
    why: str  # one line: why this kind


class Thing(_M):
    id: str
    kind: Literal["prop", "mentioned"]  # prop: a camera sees it; mentioned: only talked about or noted
    details: Value  # colour, size, material, condition


class Look(_M):
    person: str  # C id
    name: str  # "found at the canal"
    from_scene: str
    to_scene: str  # "" to the end
    outfit: str
    hair: str
    makeup: str
    accessories: str
    why: str


class Answer(_M):
    people: list[Person]
    places: list[Place]
    things: list[Thing]
    looks: list[Look]


def _strict(node: Any, defs: dict[str, Any]) -> Any:
    """Pydantic's schema -> OpenAI strict: refs inlined, every property required, no extra properties."""
    if isinstance(node, dict):
        if "$ref" in node:
            return _strict(defs[node["$ref"].split("/")[-1]], defs)
        out = {k: _strict(v, defs) for k, v in node.items() if k not in ("title", "$defs", "default")}
        if out.get("type") == "object":
            out["required"] = list(out.get("properties", {}))
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strict(v, defs) for v in node]
    return node


def json_schema() -> dict[str, Any]:
    raw = Answer.model_json_schema()
    return _strict(raw, raw.get("$defs", {}))
