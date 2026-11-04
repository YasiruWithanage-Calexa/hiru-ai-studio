"""serialize: a shot's stored design → its Veo prompt sections and free checks, in code.

    {"production": row, "persona": row | null, "canon": [rows], "scene": row, "shots": [rows], "lines": [rows],
     "shot_number": 2, "ir": {...the stored design...}, "neighbours": [row | null, row | null],
     "has_frame": false, "carried": ""}

Dialogue is placed verbatim on the beat the timing kernel bound it to; the model never writes the prompt's words.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.serialize.logic import Context, build_sections, prompt_checks
from hiru_ai.steps.serialize.model import production_input, scene_input


def run(payload: dict[str, Any]) -> dict[str, Any]:
    canon = payload.get("canon") or []
    prod = production_input(payload["production"], canon, payload.get("persona"))
    near = payload.get("neighbours") or [None, None]
    scene = scene_input(payload["scene"], payload.get("shots") or [], payload.get("lines") or [], canon, prod,
                        (near[0], near[1]))
    number = int(payload["shot_number"])
    shot = next(s for s in scene.shots if s.number == number)
    previous = next((s for s in scene.shots if s.number == number - 1), None)
    ir = dict(payload.get("ir") or shot.row.get("ir") or {})
    ctx = Context(aspect_ratio=prod.aspect_ratio, camera=shot.camera(scene), recommended=shot.recommended(scene),
                  style_note=prod.style_note, previous_code=previous.code if previous else "",
                  carried=str(payload.get("carried") or ""), has_frame=bool(payload.get("has_frame")))
    sections = build_sections(shot, ir, ctx)
    return {"sections": [s.model_dump(exclude_none=True) for s in sections],
            "checks": [c.model_dump() for c in prompt_checks(shot, sections, ctx, ir)],
            "camera": ctx.camera.model_dump()}
