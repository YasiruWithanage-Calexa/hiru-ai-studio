"""frame_compose: rows in, what a frame is made of out. JSON in, JSON out.

    {"op": "looks", "all_looks": [...], "scene_looks": [...], "episode": 1}
    {"op": "references", <world>, "shot": row}            -> {"references": [{"id", "choices": [{"label", "path"}]}]}
    {"op": "compose", <world>, "shot": row, "labels": []} -> {"prompt", "pins"}
    {"op": "expected", <world>, "shot": row}              -> {"seen", "unseen", "frame", "names"}
    {"op": "checks", <world>, "shot": row, "attached": [ids], "answer": row | null} -> {"checks": [...]}
    {"op": "reference_sheet", "production": row, "entity": row}  -> {"prompt", "aspect"}
    {"op": "look_sheet", "entity": row, "look": row}              -> {"prompt", "aspect"}

A <world> is `{"production", "canon", "scene", "lines", "looks": {character id: look}}`.
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
    if op not in ("references", "compose", "expected", "checks"):
        raise ValueError(f"unknown op {op!r}")
    world = logic.World.of(payload)
    shot = payload["shot"]
    if op == "references":
        return {"references": world.reference_choices(shot)}
    if op == "compose":
        prompt, pins = world.compose(shot, list(payload["labels"]))
        return {"prompt": prompt, "pins": pins}
    if op == "expected":
        return {**world.expected(shot), "names": world.seen_names(shot)}
    return {"checks": logic.sheet_checks(world.seen_names(shot), set(payload.get("attached") or []))
            + logic.vision_checks(payload.get("answer"), world.expected(shot))}
