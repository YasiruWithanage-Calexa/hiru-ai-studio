"""ripple: apply operations to a copy of the scene and say how the edit sits with the shots around it.

    {"scene": row, "lines": [...], "shots": [...], "canon": [...], "ops": [...], "by": "you", "summary": "..."}

The same load as `scene_kernel` (found by id): the plan before, a copy with the operations applied, then the review.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Any

from hiru_ai.core import parts
from hiru_ai.steps.ripple.logic import checked, continuity_task, review, words_line


def run(payload: dict[str, Any]) -> dict[str, Any]:
    kernel = parts.step("scene_kernel", "step").from_payload(payload)
    after = copy.deepcopy(kernel)
    result = after.apply(payload.get("ops") or [], by=str(payload.get("by") or "you"), respect_locks=False)
    rv = review(kernel, after, result.applied, result.changes)
    return {"applied": result.applied, "rejected": result.rejected, "impact": rv.impact,
            "notes": [asdict(n) for n in rv.notes], "scripted": rv.scripted, "checked": checked(rv),
            "words": words_line(kernel, after, result.changes),
            "continuity_task": continuity_task(rv, str(payload.get("summary") or ""))}
