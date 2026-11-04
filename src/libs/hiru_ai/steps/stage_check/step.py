"""stage_check: a stored shot plan in, its staging problems out.

    {"scene": row, "lines": [rows], "shots": [rows], "cast": ["Kamala"], "fixed_seconds": null}

Code finds the problems (`contracts.stagemap`): people who teleport, crossed lines, broken eyelines. The moves a
teleport needs are listed, not written; writing one is `bridges`' job. A scene with no staging map has none.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts import sceneplan, stagemap
from contracts.shotplan import fit


def run(payload: dict[str, Any]) -> dict[str, Any]:
    scene = payload["scene"]
    items = sceneplan.scene_items(scene, payload.get("lines") or [])
    staging = stagemap.SceneStaging.of(scene)
    cast = list(payload.get("cast") or [])
    fixed = payload.get("fixed_seconds")
    result = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(payload["shots"])),
                 envelope_s=int(scene["envelope_s"]), fixed_seconds=int(fixed) if fixed else None)
    return {"findings": [asdict(f) for f in stagemap.checks(staging, items, result, cast)],
            "moves": [{"before_block": b, "who": who, "zone": zone}
                      for b, who, zone in stagemap.plan_moves(staging, items, cast)],
            "unplaced": stagemap.unplaced(staging, items, cast) if staging is not None else []}
