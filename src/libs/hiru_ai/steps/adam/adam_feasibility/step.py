"""adam_feasibility: `{"scene", "moments", "cards" | "plan"}` → `{"ok", "flags", "unaddressed", "unaddressed_high",
"by_card"}`: what Veo renders badly (readable text, mirrors, fast hands, touching, crowds, a line across two takes),
with the known fix. A flag is `addressed` when the card's `veo_notes` already says how it is handled. No model."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import cards_of, errors_of, moments_of, scene_of
from hiru_ai.steps.adam.adam_feasibility import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, moments, cards = scene_of(payload), moments_of(payload), cards_of(payload)
    except ValidationError as exc:
        return {"ok": False, "flags": [], "unaddressed": 1, "unaddressed_high": 1, "by_card": {},
                "malformed": errors_of(exc)}
    return logic.check(scene, moments, cards)
