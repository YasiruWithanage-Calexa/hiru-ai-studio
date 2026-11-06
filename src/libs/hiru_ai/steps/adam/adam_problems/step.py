"""adam_problems: deterministic, no model (plan/2026-11-05 T3).

    {"scene": SceneScript, "moments": [Moment], "cards": [ShotCard]}                  rung 0: mend the mechanical faults
        → {"changed": bool, "cards": [ShotCard], "mends": [line]}
    {"reports": {"fit", "coverage", "continuity", "feasibility"}, "notes": [merged critic notes], "limit"?: int}
        → {"problems": [Problem], "left": [Problem], "counts": {mechanical, local, creative}}
"""
from __future__ import annotations

from typing import Any

from contracts.adam.plan import SceneScript, cards_of, moments_of, scene_of
from hiru_ai.steps.adam.adam_problems import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    if "reports" in payload:
        extra = {"limit": int(payload["limit"])} if payload.get("limit") else {}
        return logic.sort(dict(payload["reports"] or {}), list(payload.get("notes") or []), **extra)
    scene: SceneScript = scene_of(payload)
    cards = cards_of(payload)
    mended, mends = logic.mend(scene, moments_of(payload), cards)
    return {"changed": bool(mends), "cards": [c.model_dump(mode="json", by_alias=True) for c in mended],
            "mends": mends}
