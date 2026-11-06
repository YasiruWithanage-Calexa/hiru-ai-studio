"""story_check: the story reader's answer against the document, JSON in, JSON out.

    {"op": "check", "reading": {...reader Output...}, "text": "...", "limit": 60000} → {"story": {...}}
    {"op": "loads", "raw": "...", "text": "..."}                                     → {"story": {...} | None}
    {"op": "path", "text_path": "p/d/extracted.txt"}                                 → {"path": "p/d/story.json"}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.story_check import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "check":
        return {"story": logic.check(payload["reading"], payload["text"], limit=payload.get("limit"))}
    if op == "loads":
        return {"story": logic.loads(payload["raw"], payload["text"])}
    if op == "path":
        return {"path": logic.story_path(payload["text_path"])}
    raise ValueError(f"unknown op {op!r}")
