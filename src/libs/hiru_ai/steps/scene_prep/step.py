"""scene_prep: a scene in, its script prepared by the rules alone (no model). JSON in, JSON out.

    {"scene": row, "lines": [rows], "cast": ["Kamala"]}

The same code the system runs around its three model calls, with every `ask` left out: the script gets its implied steps
and every action block is read by the free rules, the reading is the rules' (or the stored one), and a stored
staging map is kept (no map is made without a model). It shows what a scene looks like with no key.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.scene_prep import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene, lines = payload["scene"], payload.get("lines") or []
    cast = list(payload.get("cast") or [])
    script, items = logic.prepare(scene, lines, None, cast)
    reading, _ = logic.reading_for(scene, items, None, cast)
    names = {str(i): n for i, n in enumerate(cast)}
    script, items, reading, staging = logic.stage(scene, lines, script, items, reading, None, names)
    return {"script": script, "blocks": len(items), "reading": reading.model_dump(mode="json"),
            "staging": staging.model_dump(mode="json") if staging is not None else None}
