"""Clip-schema loader — the single source of truth for turning a shot into a Veo prompt.

Forked from PromptMotion `nova_producer/engine/schema.py` (1d748dc). The constant rules a video
model must obey and the IR the director-of-photography model fills live in a per-engine YAML,
not scattered through code. Hiru adds `json_schema()`: every model call here uses OpenAI's
strict structured output (CLAUDE.md), so the YAML's field hints become the schema's
descriptions instead of a template pasted into the prompt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from contracts.producer import CAMERA_OPTIONS, CameraField

_SCHEMAS_DIR = Path(__file__).parent / "schemas"

VIDEO_ENGINE_SCHEMAS = {"veo_3_1": "clip_schema_veo_3_1"}

# The camera fields the DP recommends from the panel's own choices. Framing is not one of them:
# the director fixed the shot size in the Director panel.
RECOMMENDED_FIELDS: tuple[CameraField, ...] = tuple(f for f in CameraField if f is not CameraField.FRAMING)


def _structure_to_template(node: Any) -> Any:
    if isinstance(node, dict):
        if "_item" in node:
            return [_structure_to_template(node["_item"])]
        return {k: _structure_to_template(v) for k, v in node.items()}
    return node


def _to_json_schema(node: Any) -> dict[str, Any]:
    """YAML structure → strict JSON schema: every object closed and every key required."""
    if isinstance(node, dict):
        if "_item" in node:
            return {"type": "array", "items": _to_json_schema(node["_item"])}
        return {"type": "object", "additionalProperties": False, "required": list(node),
                "properties": {k: _to_json_schema(v) for k, v in node.items()}}
    return {"type": "string", "description": str(node)}


@dataclass
class ClipSchema:
    fixed_values: dict[str, str] = field(default_factory=dict)
    render_rules: dict[str, str] = field(default_factory=dict)
    required_keys: list[str] = field(default_factory=list)
    coerce_to_list: list[str] = field(default_factory=list)
    required_structure: dict[str, Any] = field(default_factory=dict)

    def rule(self, name: str) -> str:
        """A constant rule string by name — fixed_values first, then render_rules, '' if unknown."""
        return self.fixed_values.get(name) or self.render_rules.get(name) or ""

    def template_json(self) -> str:
        return json.dumps(_structure_to_template(self.required_structure), indent=2, ensure_ascii=False)

    def shot_schema(self) -> dict[str, Any]:
        """One shot's IR plus the DP's camera recommendation (from the panel's choices) and why."""
        base = _to_json_schema(self.required_structure)
        rec = {"type": "object", "additionalProperties": False, "required": [f.value for f in RECOMMENDED_FIELDS],
               "properties": {f.value: {"type": "string", "enum": list(CAMERA_OPTIONS[f])} for f in RECOMMENDED_FIELDS}}
        props = {"number": {"type": "integer", "description": "The shot number this IR is for."},
                 **base["properties"], "recommendation": rec,
                 "rationale": {"type": "string",
                               "description": "One or two sentences: why this lens, move and light serve the moment."}}
        return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}

    def scene_schema(self) -> dict[str, Any]:
        """A whole scene in one answer: one IR per shot, matched back BY NUMBER, never position."""
        return {"type": "object", "additionalProperties": False, "required": ["shots"],
                "properties": {"shots": {"type": "array", "items": self.shot_schema()}}}

    def coerce(self, ir: dict[str, Any]) -> dict[str, Any]:
        out = dict(ir or {})
        for name in self.coerce_to_list:
            v = out.get(name)
            if isinstance(v, list):
                continue
            out[name] = [v] if isinstance(v, dict) else []
        return out

    def missing_keys(self, ir: dict[str, Any]) -> list[str]:
        return [k for k in self.required_keys if not (ir or {}).get(k)]


@cache
def get_schema(video_engine: str = "veo_3_1") -> ClipSchema:
    stem = VIDEO_ENGINE_SCHEMAS.get(video_engine or "veo_3_1")
    if not stem:
        raise ValueError(f"no clip schema for video_engine {video_engine!r}")
    with (_SCHEMAS_DIR / f"{stem}.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ClipSchema(
        fixed_values=data.get("fixed_values") or {},
        render_rules=data.get("render_rules") or {},
        required_keys=[k.split("#")[0].strip() for k in (data.get("required_keys") or [])],
        coerce_to_list=data.get("coerce_to_list") or [],
        required_structure=data.get("required_structure") or {},
    )
