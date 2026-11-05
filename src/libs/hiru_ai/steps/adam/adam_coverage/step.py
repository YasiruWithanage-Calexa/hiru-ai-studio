"""adam_coverage: the coverage grid of a plan (plan/2026-11-04c §4 F2).

    {"scene": SceneScript, "plan": AdamPlan}
        → {"cells": [{id, kind, who, blocks, why, ok, card}], "holes": [{cell, kind, who, blocks, why, card, suggest}],
           "required", "filled", "coverage", "grid": {"people", "beats": [{beat, blocks, turn, faces}]}}
    {"scene": SceneScript, "analysis": SceneAnalysis, "treatment": Treatment}     (no cards yet: for the designer)
        → {"required": [line, ...]}      the faces that must be seen, in words

Pure code. A cell is filled from a card's subject and framing, never from a model's claim.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import AdamPlan, SceneAnalysis, Treatment, errors_of, scene_of
from hiru_ai.steps.adam.adam_coverage import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene = scene_of(payload)
        if "plan" not in payload:
            analysis = SceneAnalysis.model_validate(payload.get("analysis"))
            treatment = Treatment.model_validate(payload.get("treatment"))
            return {"required": logic.lines(logic.required(scene, analysis, treatment))}
        return logic.check(scene, AdamPlan.model_validate(payload["plan"]))
    except ValidationError as exc:
        return {"cells": [], "holes": [], "required": 0, "filled": 0, "coverage": 1.0, "grid": {},
                "malformed": errors_of(exc)}
