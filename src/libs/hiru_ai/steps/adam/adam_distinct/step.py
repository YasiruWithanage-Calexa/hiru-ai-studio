"""adam_distinct: `{"treatments": [Treatment], "expected": 3?}` → `{"ok", "count", "issues", "pairs"}`: do a scene's
treatments differ on purpose? Deterministic, no model (plan/2026-11-04b §10, Phase 3)."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import Treatment, errors_of
from hiru_ai.steps.adam.adam_distinct import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        treatments = [Treatment.model_validate(t) for t in payload.get("treatments") or []]
    except ValidationError as exc:
        issue = {"code": "malformed", "where": "the treatments", "message": errors_of(exc)}
        return {"ok": False, "count": 1, "issues": [issue], "pairs": []}
    return logic.check(treatments, int(payload.get("expected", 3)))
