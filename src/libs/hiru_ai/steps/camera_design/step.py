"""camera_design: the code around the `camera_agent` (plan/2026-11-20c §4). JSON in, JSON out, no model, no database.

    {"op": "brief", "scene_text": str, "clips": [...], "ideas"?: {slate: [[move, why]]}}
        -> {"scene": str, "clips": str}
    {"op": "check", "answer": {...}, "clips": [...], "focus"?: [slate]}
        -> {"faults": [...], "notes": [...]}
    {"op": "merge", "design": {...}, "clip"?: {...}, "base": {...}, "language": str, "model": str, "job_id": str,
     "faults"?: [...]}
        -> {"design": {...}}

`clips` are the dicts `facts.clip_facts` builds from the shot producer's rows. A system calls the agent between `brief`
and `check`, gives a failed answer ONE repair with the faults, and merges what passes; a clip still faulty keeps the
rule recommendation (D10). The runner that does all of it for a scene is `hiru_ai.core.camera`.
"""
from __future__ import annotations

from typing import Any

from contracts.producer import CameraSettings
from hiru_ai.steps.camera_design import brief, gates, merge


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "brief":
        ideas = {k: [tuple(i) for i in v] for k, v in (payload.get("ideas") or {}).items()}
        return {"scene": brief.scene_part(str(payload.get("scene_text") or "")),
                "clips": brief.clips_part(payload.get("clips") or [], ideas)}
    if op == "check":
        faults, notes = gates.check_scene(payload["answer"], payload.get("clips") or [],
                                          focus=list(payload.get("focus") or []), locked=bool(payload.get("locked")))
        return {"faults": faults, "notes": notes}
    if op == "merge":
        base = CameraSettings.model_validate(payload["base"])
        return {"design": merge.merged(payload.get("design") or {}, payload.get("clip"), base=base,
                                       language=str(payload.get("language") or ""),
                                       model=str(payload.get("model") or ""), job_id=str(payload.get("job_id") or ""),
                                       faults=list(payload.get("faults") or []),
                                       arc=str(payload.get("arc") or ""), peak=str(payload.get("peak") or ""))}
    raise ValueError(f"unknown op {op!r}")
