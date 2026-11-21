"""shot_prompt: the code around the `shot_prompter` agent (plan/2026-11-20d §4 phase 3). JSON in, JSON out, no model.

    {"op": "camera", "settings": {...}, "block": {...} | null, "sentence": str}   -> {"camera": {...}}
    {"op": "brief", "facts": {...}}                                              -> {"shot", "camera", "cards"}
    {"op": "check", "answer": {...}, "facts": {...}, "mode": "both"|"video_only"} -> {"faults": [str]}
    {"op": "fixed", "answer": {...}, "stored": {...}}                            -> {"answer": {...}}
    {"op": "direction", "answer": {...}}                                         -> {"direction": {...}}
    {"op": "frame", "record": {...}}                                             -> {"frame": {...}}
    {"op": "record", "answer": {...}, "model", "job_id", "pins", "mode", "repaired"} -> {"record": {...}}

`facts` is the `video_prompt` step's clip facts plus `first_frame`, `opens_state` and `camera` (the "camera" op). A
system calls the agent between `brief` and `check`, gives a failed answer ONE repair with the faults, and stores nothing
when the faults remain (D6). The video is assembled by the `video_prompt` step from `direction` (D1).
"""
from __future__ import annotations

from typing import Any

from hiru_ai.core import parts
from hiru_ai.steps.shot_prompt import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "camera":
        return {"camera": logic.camera_facts(payload.get("settings") or {}, payload.get("block"),
                                             str(payload.get("sentence") or ""))}
    if op == "brief":
        facts = payload["facts"]
        cards = parts.step("video_prompt", "logic").cards_for(facts)
        return {"shot": logic.shot_brief(facts), "camera": logic.camera_brief(facts.get("camera") or {}),
                "cards": cards}
    if op == "check":
        return {"faults": logic.check(payload["answer"], payload["facts"], mode=str(payload.get("mode") or "both"))}
    if op == "fixed":
        return {"answer": logic.fixed_answer(payload["answer"], payload.get("stored"))}
    if op == "direction":
        return {"direction": logic.direction(payload["answer"])}
    if op == "frame":
        return {"frame": logic.frame_parts(payload.get("record"))}
    if op == "record":
        return {"record": logic.record(payload["answer"], model=str(payload.get("model") or ""),
                                       job_id=str(payload.get("job_id") or ""), pins=payload.get("pins") or {},
                                       mode=str(payload.get("mode") or "both"),
                                       repaired=bool(payload.get("repaired")))}
    raise ValueError(f"unknown op {op!r}")
