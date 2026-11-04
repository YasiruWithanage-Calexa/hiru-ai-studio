"""adam_fidelity: `{"scene": SceneScript, "moments": [...] | "plan": {...}, "cards": [...]?}` →
`{"ok", "breaks", "dropped", "kept", "send_back", "counts"}`. Deterministic, no model (plan/2026-11-04b §6.1)."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import cards_of, errors_of, moments_of, part_of, scene_of
from hiru_ai.steps.adam.adam_fidelity import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        scene, moments = scene_of(payload), moments_of(payload)
        cards = cards_of(payload) if part_of(payload, "cards") is not None else None
    except ValidationError as exc:
        return {"ok": False, "send_back": True, "dropped": [], "kept": [], "counts": {},
                "breaks": [{"code": "malformed", "where": "the plan", "reason": errors_of(exc), "fix": "send_back",
                            "moment": ""}]}
    return logic.check(scene, moments, cards)
