"""kernel_score: a stored shot plan in, its score out (lower is better, compared left to right).

    {"scene": row, "lines": [rows], "shots": [rows], "cast": ["Kamala"], "fixed_seconds": null}

The scene's reading and staging map are read from the scene row, as the splitter does.
"""
from __future__ import annotations

from typing import Any

from contracts import sceneplan, stagemap
from contracts.reading import SceneReading
from contracts.shotplan import fit
from hiru_ai.steps.kernel_score.logic import describe, kernel_score


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene = payload["scene"]
    items = sceneplan.scene_items(scene, payload.get("lines") or [])
    fixed = payload.get("fixed_seconds")
    result = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(payload["shots"])),
                 envelope_s=int(scene["envelope_s"]), fixed_seconds=int(fixed) if fixed else None)
    score = kernel_score(result, SceneReading.of(scene), items, stagemap.SceneStaging.of(scene),
                         list(payload.get("cast") or []))
    return {"score": list(score), "issues": [i.code for i in result.issues], "total_s": result.total_s,
            "described": describe(result, items)}
