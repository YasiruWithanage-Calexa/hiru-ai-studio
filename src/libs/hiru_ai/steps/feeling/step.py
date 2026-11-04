"""feeling: what one shot must play, from the scene's reading and staging map.

    {"scene": row, "lines": [rows], "shot": row, "cast": ["Kamala"]}      (the shot row's block range and beats)

`Feeling` is what a shot design is written from (the DoP's PERFORMANCE block) and what the free check
`performance_missing` holds the draft to.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts import reading as rd
from contracts import sceneplan, stagemap
from contracts.producer import shot_items
from hiru_ai.steps.feeling.logic import feeling_for, positions_text


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene, shot = payload["scene"], payload["shot"]
    items = sceneplan.scene_items(scene, payload.get("lines") or [])
    windows = [(int(b["start_s"]), int(b["end_s"])) for b in shot.get("beats") or []]
    own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
    feeling = feeling_for(rd.SceneReading.of(scene), stagemap.SceneStaging.of(scene), items, own, windows,
                          list(payload.get("cast") or []))
    return {"beat_notes": {str(k): v for k, v in feeling.beat_notes.items()}, "turn_beats": sorted(feeling.turn_beats),
            "wants": feeling.wants, "person_wants": feeling.person_wants,
            "start": [asdict(p) for p in feeling.start], "end": [asdict(p) for p in feeling.end],
            "start_text": positions_text(feeling.start), "end_text": positions_text(feeling.end),
            "performance": feeling.performance_text(windows)}
