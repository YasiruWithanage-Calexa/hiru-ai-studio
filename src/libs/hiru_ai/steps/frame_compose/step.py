"""frame_compose: rows in, what a frame is made of out. JSON in, JSON out.

    {"op": "looks", "all_looks": [...], "scene_looks": [...], "episode": 1}
    {"op": "references", <world>, "shot": row}            -> {"references": [{"id", "role", "choices": [{"label",
                                                              "path", "bucket"}]}]}
    {"op": "compose", <world>, "shot": row, "labels": []} -> {"prompt", "pins"}
    {"op": "expected", <world>, "shot": row}              -> {"seen", "unseen", "frame", "hands", "names"}
    {"op": "brief", <world>, "shot": row, "polished": bool} -> {"sections": [{key, title, text, sources}], "names"}
    {"op": "checks", <world>, "shot": row, "attached": [ids], "answer": row | null} -> {"checks": [...]}
    {"op": "reference_sheet", "production": row, "entity": row}  -> {"prompt", "aspect"}
    {"op": "look_sheet", "entity": row, "look": row}              -> {"prompt", "aspect"}

A <world> is `{"production", "canon", "scene", "lines", "looks": {character id: look}, "shots": [...], "accepted": {shot
id: frame}}`; `shots` and `accepted` (the scene's accepted finals) give a later shot of a setup its same-setup frame
(plan/2026-11-11b) and may be left out.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.frame_compose import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "looks":
        return {"looks": logic.looks_for_scene(payload["all_looks"], payload["scene_looks"], payload.get("episode"))}
    if op == "reference_sheet":
        prompt, aspect = logic.reference_sheet(payload["production"], payload["entity"])
        return {"prompt": prompt, "aspect": aspect}
    if op == "look_sheet":
        return {"prompt": logic.look_sheet(payload["entity"], payload["look"]), "aspect": logic.ASPECT_OF_SHEET}
    if op not in ("references", "compose", "expected", "checks", "brief"):
        raise ValueError(f"unknown op {op!r}")
    world = logic.World.of(payload)
    shot = payload["shot"]
    if op == "references":
        return {"references": world.reference_choices(shot)}
    if op == "compose":
        prompt, pins = world.compose(shot, list(payload["labels"]))
        return {"prompt": prompt, "pins": pins}
    if op == "brief":  # the prompt as the shot screen shows it, by section (plan/2026-11-11c: the writer's input)
        brief = world.brief(shot, world.preview_labels(shot), polished=bool(payload.get("polished", True)))
        return {"sections": brief.view(), "names": world.names()}
    if op == "expected":
        return {**world.expected(shot), "names": world.seen_names(shot)}
    return {"checks": logic.sheet_checks(world.seen_names(shot), set(payload.get("attached") or []))
            + logic.vision_checks(payload.get("answer"), world.expected(shot))}
