"""split_write: a fitted scene in, the rows and reports to write out. JSON in, JSON out.

    {"scene": row, "lines": [rows], "shots": [rows], "planner": "rules", "notes": [], "label": "Ep 01 Scene 1"}

The shots are the stored plan, fitted again by the kernel (as `kernel_score` does); what comes back is what the splitter
writes for the scene: `shots`, `lines`, `fit_report`, and the free continuity notes.
"""
from __future__ import annotations

from typing import Any

from contracts import sceneplan
from contracts.shotplan import fit
from hiru_ai.steps.split_write import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene, lines = payload["scene"], payload.get("lines") or []
    items = sceneplan.scene_items(scene, lines)
    fixed = payload.get("fixed_seconds")
    result = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(payload["shots"])),
                 envelope_s=int(scene["envelope_s"]), fixed_seconds=int(fixed) if fixed else None)
    shots, line_rows = logic.rows_for(scene, result, lines)
    planner, notes = str(payload.get("planner") or "rules"), list(payload.get("notes") or [])
    return {"shots": shots, "lines": line_rows, "fit_report": logic.report(result, planner, notes),
            "continuity": logic.continuity_notes(str(payload.get("label") or "Scene"), scene, lines),
            "episode_stats": logic.episode_stats(result, scene)}
