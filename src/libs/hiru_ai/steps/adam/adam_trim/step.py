"""adam_trim: `{"cards": [ShotCard]}` → `{"cards": [...with use_s and in_s], "notes": [line], "runtime_s", "saved_s"}`.

Deterministic, no model (plan/2026-11-04b §5.6, Phase 9). Used only when the production's final cut trims takes
(`settings.final_cut_trim`); otherwise every take plays whole."""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.editorial import plan_cuts, propose_trims, runtime_s
from contracts.adam.plan import ShotCard, errors_of


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        cards = [ShotCard.model_validate(c) for c in payload.get("cards") or []]
    except ValidationError as exc:
        return {"cards": [], "notes": [], "malformed": errors_of(exc)}
    trimmed, notes = propose_trims(cards)
    kept = runtime_s(plan_cuts(trimmed, editorial=True))
    return {"cards": [c.model_dump(mode="json", by_alias=True) for c in trimmed], "notes": notes,
            "runtime_s": kept, "saved_s": sum(c.take_s for c in cards) - kept}
