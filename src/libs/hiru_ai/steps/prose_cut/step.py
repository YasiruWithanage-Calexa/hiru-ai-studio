"""prose_cut: `{"op": "to_cut", "text": "..."}` → the episodes to cut; `{"op": "by_rules", "section": {...}}` → scenes.

    {"op": "to_cut", "text": "...", "story": {...}?}                 → {"sections": [...]} or {"sections": []}
    {"op": "by_rules", "section": {number, title, duration_s, body}} → {"scenes": [...]}
    {"op": "trusted", "section": {...}, "scenes": [...]}             → {"trusted": bool}
    {"op": "render", "scenes": [...]}                                → {"text": "..."}
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from hiru_ai.steps.prose_cut import logic


def _section(data: dict[str, Any]) -> logic.Section:
    return logic.Read(**data) if "spoken" in data else logic.Section(**data)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "to_cut":
        return {"sections": [asdict(s) for s in logic.to_cut(payload["text"], payload.get("story")) or []]}
    section = _section(payload["section"]) if "section" in payload else None
    if op == "by_rules" and section:
        return {"scenes": logic.by_rules(section)}
    if op == "trusted" and section:
        return {"trusted": logic.trusted(section, payload["scenes"])}
    if op == "render":
        return {"text": logic.render(payload["scenes"])}
    raise ValueError(f"unknown op {op!r}")
