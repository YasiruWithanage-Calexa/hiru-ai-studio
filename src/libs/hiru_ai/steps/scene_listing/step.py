"""scene_listing: a scene's blocks in, the listing the model reads out.

    {"scene": row, "lines": [rows], "speaker_names": {"<speaker_id>": "Kamala"}}

The scene's reading marks (holds, feeling turns) are read from the scene row, as the splitter does.
"""
from __future__ import annotations

from typing import Any

from contracts import sceneplan
from hiru_ai.steps.scene_listing.logic import scene_listing


def run(payload: dict[str, Any]) -> dict[str, Any]:
    items = sceneplan.scene_items(payload["scene"], payload.get("lines") or [])
    return {"listing": scene_listing(items, dict(payload.get("speaker_names") or {})), "blocks": len(items)}
