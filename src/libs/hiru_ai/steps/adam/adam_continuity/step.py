"""adam_continuity: `{"moments", "cards", "staging"? | "plan"}` → `{"ok", "issues", "count"}`: the 180° line, eyelines
and screen direction, a person in two places without a move, props that change hands unseen. No model."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import Staging, cards_of, errors_of, moments_of, part_of
from hiru_ai.steps.adam.adam_continuity import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        moments, cards = moments_of(payload), cards_of(payload)
        staging = Staging.model_validate(part_of(payload, "staging") or {})
    except ValidationError as exc:
        issue = {"code": "malformed", "where": "the plan", "message": errors_of(exc)}
        return {"ok": False, "count": 1, "issues": [issue]}
    return logic.check(cards, moments, staging)
