"""adam_notes: deterministic, no model.

    {"results": [{"lens", "score", "notes": [{"card", "severity", "note"}]} | null, ...]}
        → {"notes": [line], "scores": {lens: 1-5}, "failed": int, "kept": [...], "dropped": int}
    {"fidelity", "fit", "continuity", "feasibility", "coverage"?, "score"?}   (the other Adam steps' answers)
        → {"text": the code's findings as lines a critic reads, "problems": how many are open}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.adam.adam_notes import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    if "results" in payload:
        return logic.merge(list(payload["results"] or []))
    keys = ("fidelity", "fit", "continuity", "feasibility", "coverage", "score")
    return logic.report({k: payload.get(k) or {} for k in keys})
