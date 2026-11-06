"""memory_conflicts: the production's memory entries in, the conflicts out. No model.

    {"entries": [...rows...], "documents": {"<document id>": "<created_at>"}} → {"conflicts": [{"kind", "ids", "text"}]}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.memory_conflicts import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return {"conflicts": logic.find(payload["entries"], payload.get("documents") or {})}
