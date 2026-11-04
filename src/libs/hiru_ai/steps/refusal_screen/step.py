"""refusal_screen: JSON in, JSON out. `{"reason": "..."}` → `{"text": "..."}`."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.refusal_screen.logic import for_person


def run(payload: dict[str, Any]) -> dict[str, Any]:
    return {"text": for_person(str(payload.get("reason") or ""))}
