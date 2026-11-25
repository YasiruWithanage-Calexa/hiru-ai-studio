"""frame_compose: rows in, what a frame is made of out. JSON in, JSON out.

    {"op": "looks", "all_looks": [...], "scene_looks": [...], "episode": 1}
    {"op": "references", <world>, "shot": row, "panel": {..}?} -> {"references": [{"id", "role", "choices": [{"label",
                                                              "path", "bucket"}]}]}
    {"op": "compose", <world>, "shot": row, "labels": [], "board": [..]?, "panel": {..}?} -> {"prompt", "pins"}

`panel` (plan/2026-11-25b): the frame's board panel, `{props, colours, words}` (`frame_render.graph._board_panel`);
its props' sheets are attached and its stand-ins bound to them in the prompt.
    {"op": "expected", <world>, "shot": row}              -> {"seen", "unseen", "frame", "hands", "names"}
    {"op": "brief", <world>, "shot": row}                -> {"sections": [{key, title, text, sources}], "names"}
    {"op": "shot_prompt", <world>, "shot": row}          -> {"reasons": [...], "pins": {...}} (plan/2026-11-20d D8:
                                                              why its stored shot prompt is out of date; pins now)
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
    if op not in ("references", "compose", "expected", "checks", "brief", "plate", "shot_prompt"):
        raise ValueError(f"unknown op {op!r}")
    world = logic.World.of(payload)
    shot = payload["shot"]
    if op == "references":
        return {"references": world.reference_choices(shot, payload.get("panel"))}
    if op == "plate":  # plan/2026-11-12b: a black plate is made by code, never painted
        return {"plate": world.plate(shot)}
    if op == "compose":
        prompt, pins = world.compose(shot, list(payload["labels"]), list(payload.get("board") or []) or None,
                                    payload.get("panel"))
        return {"prompt": prompt, "pins": pins}
    if op == "brief":  # the prompt as the shot screen shows it, by section
        brief = world.brief(shot, world.preview_labels(shot))
        return {"sections": brief.view(), "names": world.names()}
    if op == "shot_prompt":
        return {"reasons": world.shot_prompt_reasons(shot), "pins": world.pins_now(shot)}
    if op == "expected":
        return {**world.expected(shot, list(payload.get("board") or []) or None), "names": world.seen_names(shot)}
    return {"checks": logic.sheet_checks(world.seen_names(shot), set(payload.get("attached") or []))
            + logic.vision_checks(payload.get("answer"), world.expected(shot, list(payload.get("board") or [])
                                                                       or None))}
