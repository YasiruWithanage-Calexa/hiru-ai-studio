"""adam_score: the craft score, by code (plan/2026-11-04b §6.2).

    {"scene": SceneScript, "plan": AdamPlan, "weights"?: {...}, "fidelity"?, "fit"?, "feasibility"?, "coverage"?}
        → {"loss", "loss_reasons", "score", "max", "percent", "signals": [{signal, points, checks: [{card, ok, why}]}]}
    {"scene": ..., "plans": [AdamPlan, ...]}      → the same for each, and `chosen`: the best by (fewer fidelity breaks
        and required cells lost to another plan, fewer overruns, more craft); a tie keeps the EARLIER plan, so a
        revision has to be better to replace the first.

The code reports are asked of the other Adam steps by id (`core.parts`) unless the caller already has them.
"""
from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.adam.plan import AdamPlan, errors_of, scene_of
from hiru_ai.core import parts
from hiru_ai.steps.adam.adam_score import logic


def _report(step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return dict(parts.module("step", step_id, "step").run(payload))


def score_one(scene_raw: Any, plan_raw: Any, payload: dict[str, Any]) -> dict[str, Any]:
    scene, plan = scene_of({"scene": scene_raw}), AdamPlan.model_validate(plan_raw)
    base = {"scene": scene_raw, "plan": plan_raw}
    fidelity = payload.get("fidelity") or _report("adam_fidelity", base)
    fit = payload.get("fit") or _report("adam_fit", base)
    feasible = payload.get("feasibility") or _report("adam_feasibility", base)
    covered = payload.get("coverage") or _report("adam_coverage", base)
    return logic.score(scene, plan, fidelity, fit, feasible, payload.get("weights"), covered)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if "plans" in payload:
            results = [score_one(payload.get("scene"), p, {"weights": payload.get("weights")})
                       for p in payload["plans"]]
            if not results:
                return {"results": [], "chosen": None}
            lost = logic.lost_cells(results)
            chosen = min(range(len(results)), key=lambda i: (logic.rank(results[i], lost[i]), i))
            return {"results": results, "chosen": chosen}
        return score_one(payload.get("scene"), payload.get("plan"), payload)
    except ValidationError as exc:
        return {"loss": True, "loss_reasons": ["the plan could not be read: " + errors_of(exc)], "score": 0.0,
                "max": 0.0, "percent": 0.0, "fidelity_breaks": 1, "overruns": 0, "signals": [], "malformed": True}
