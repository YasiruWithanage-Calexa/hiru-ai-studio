"""rules_plan: a scene's blocks in, the rules' shot plan out. JSON in, JSON out.

    {"scene": row, "lines": [rows], "envelope_s": 24, "fixed_seconds": null}

The scene's reading is applied first (its holds and feeling turns), as the splitter does. The plan is the rules' own
shots after `fold_breath`, fitted by the kernel; the model's plan is a different part (`scene_planner`).
"""
from __future__ import annotations

from typing import Any

from contracts import reading as scene_reading
from contracts import sceneplan
from contracts.shotplan import fit
from hiru_ai.steps.rules_plan import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene = payload["scene"]
    items = scene_reading.apply(sceneplan.scene_items(scene, payload.get("lines") or []),
                                scene_reading.SceneReading.of(scene))
    envelope = int(payload.get("envelope_s") or scene["envelope_s"])
    fixed = payload.get("fixed_seconds")
    kept, shots = logic.rules_plan(items, envelope_s=envelope, fixed_seconds=int(fixed) if fixed else None)
    result = fit(kept, shots, envelope_s=envelope, fixed_seconds=int(fixed) if fixed else None)
    return {"shots": [{"start": s.start, "end": s.end, "framing": s.framing, "title": s.title,
                       "sound_mode": s.sound_mode.value, "duration_s": s.duration_s} for s in result.shots],
            "total_s": result.total_s, "issues": [i.code for i in result.issues]}
