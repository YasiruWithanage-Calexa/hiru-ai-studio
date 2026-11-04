"""adam_distinct: `{"treatments": [Treatment], "expected": 3?}` → `{"ok", "count", "issues", "pairs"}`: do a scene's
treatments differ on purpose? With `"analysis": SceneAnalysis` it also CHOOSES one (`{"index", "stance", "scores"}`),
the quick score on the treatments alone that picks when no person has (plan/2026-11-04b §5.5). Deterministic, no
model (Phase 3)."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import SceneAnalysis, Treatment, errors_of
from hiru_ai.steps.adam.adam_distinct import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        treatments = [Treatment.model_validate(t) for t in payload.get("treatments") or []]
    except ValidationError as exc:
        issue = {"code": "malformed", "where": "the treatments", "message": errors_of(exc)}
        return {"ok": False, "count": 1, "issues": [issue], "pairs": []}
    out = logic.check(treatments, int(payload.get("expected", 3)))
    if payload.get("analysis") is not None:
        try:
            out["choice"] = logic.choose(treatments, SceneAnalysis.model_validate(payload["analysis"]))
        except ValidationError as exc:
            out["choice"] = {"index": None, "stance": "", "scores": [], "malformed": errors_of(exc)}
    return out
