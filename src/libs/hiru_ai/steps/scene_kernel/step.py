"""scene_kernel: load a scene's rows into the kernel, apply operations, report what landed.

    {"scene": row, "lines": [rows], "shots": [rows], "canon": [rows], "fixed_seconds": null,
     "ops": [{"op": "set", "shot": 2, "field": "framing", "value": "CU"}], "by": "conductor"}

`kernel_for` is also what `ripple` and the director's graphs use to get a kernel (by id, through `core.parts`).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts import sceneplan
from hiru_ai.steps.scene_kernel.logic import ScenePlanKernel


def kernel_for(scene: dict[str, Any], lines: list[dict[str, Any]], shots: list[dict[str, Any]],
               fixed: int | None, canon: list[dict[str, Any]] | None = None) -> ScenePlanKernel:
    """A scene's stored rows → its kernel (the same load the director does for a turn)."""
    items = [sceneplan.item_row(i) for i in sceneplan.scene_items(scene, lines)]
    by_line = {str(ln["id"]): ln for ln in lines}
    for item in items:  # a translated line carries the words it was written in
        stored = by_line.get(str(item.get("line_id")), {})
        item |= {k: stored[k] for k in sceneplan.LINE_SOURCE if stored.get(k)}
    # An unlocked length travels as the planner's choice: kept unless the speech needs longer.
    return ScenePlanKernel(items, sceneplan.plan_from_rows(shots), envelope_s=int(scene["envelope_s"]),
                           fixed_seconds=fixed, canon=canon,
                           location_id=str(scene["location_id"]) if scene.get("location_id") else None)


def from_payload(payload: dict[str, Any]) -> ScenePlanKernel:
    fixed = payload.get("fixed_seconds")
    return kernel_for(payload["scene"], payload.get("lines") or [], payload.get("shots") or [],
                      int(fixed) if fixed else None, payload.get("canon"))


def run(payload: dict[str, Any]) -> dict[str, Any]:
    kernel = from_payload(payload)
    allowed = payload.get("allowed_ops")
    result = kernel.apply(payload.get("ops") or [], by=str(payload.get("by") or "conductor"),
                          respect_locks=bool(payload.get("respect_locks", True)),
                          allowed_ops=tuple(allowed) if allowed is not None else None)
    return {"applied": result.applied, "rejected": result.rejected, "changes": [asdict(c) for c in result.changes],
            "shots": kernel.shots, "items": kernel.items, "notes": kernel.notes,
            "script_changed": kernel.script_changed, "described": kernel.describe()}
