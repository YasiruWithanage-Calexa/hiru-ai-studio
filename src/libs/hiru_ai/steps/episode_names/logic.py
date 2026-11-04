"""What the architect's answer changes in an episode: its synopsis (only when empty) and its scene titles. Ported from
`structure_build/engine/architect.py` (`name_all`, plan/2026-11-03 Phase 6)."""
from __future__ import annotations

from typing import Any

SYNOPSIS_CHARS = 2000
TITLE_CHARS = 80


def input_for(episode: dict[str, Any]) -> dict[str, Any]:
    """The `architect` agent's input for one episode."""
    return {"number": episode["number"], "title": episode["title"],
            "scenes": [{"number": s["number"], "heading": s["heading"]["raw"],
                        "blocks": [{"kind": b["kind"], "speaker": b["speaker"], "text": b["text"]}
                                   for b in s["blocks"]]} for s in episode["scenes"]]}


def apply(episode: dict[str, Any], synopsis: str, scenes: list[dict[str, Any]]) -> None:
    """Fill `synopsis` (when empty) and scene titles in place."""
    if not episode["synopsis"] and synopsis:
        episode["synopsis"] = " ".join(str(synopsis).split())[:SYNOPSIS_CHARS]
    titles = {int(s["number"]): " ".join(str(s["title"]).split())[:TITLE_CHARS] for s in scenes}
    for scene in episode["scenes"]:
        if titles.get(scene["number"]):
            scene["title"] = titles[scene["number"]]
