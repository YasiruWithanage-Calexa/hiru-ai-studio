"""adam_fit: `{"scene", "moments", "cards" | "plan", "editorial"?}` → the Veo clock for every card
(`ok`, `cards`, `issues`, `overruns`, `runtime_s`, `over_envelope_s`). Deterministic, no model. Reports overruns,
never trims a line."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import cards_of, errors_of, moments_of, scene_of
from hiru_ai.steps.adam.adam_fit import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, moments, cards = scene_of(payload), moments_of(payload), cards_of(payload)
    except ValidationError as exc:
        return {"ok": False, "cards": [], "overruns": 1, "runtime_s": 0, "malformed": errors_of(exc),
                "issues": [{"code": "malformed", "level": "overrun", "message": errors_of(exc), "card": None,
                            "line_id": None}]}
    return logic.check(scene, moments, cards, editorial=bool(payload.get("editorial")))
