"""zora_kernel: `{"doc": {plan, scene, person}, "ops": [...], "by", "allowed_ops"?, "planner_check"?}` →
`{"applied", "rejected", "staged", "changes", "plan", "person"}` (plan/2026-11-06e §4.2).

Deterministic, no model. `planner_check` (default true) re-checks the plan after every operation with the planner's own
validation, reached by id; the kernel's pure shape check runs always. The rules are `logic.ZoraKernel`.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from contracts.zora.doc import ZoraDoc
from hiru_ai.core import parts
from hiru_ai.steps.zora.zora_kernel.logic import Validate, ZoraKernel

PLANNER_CHECK = "jonathan_check"  # the planner whose stored plan Zora edits (tests/zora/test_removal.py)


def planner_validation(scene: dict[str, Any]) -> Validate:
    """The planner's own wire validation of a whole plan, by id ([] = it reads)."""
    check = parts.step(PLANNER_CHECK, "step")

    def validate(plan: dict[str, Any]) -> list[str]:
        out = check.run({"scene": scene, "plan": plan})
        return [str(out["malformed"])] if out.get("malformed") else []

    return validate


def kernel_for(doc: ZoraDoc, *, planner_check: bool = True) -> ZoraKernel:
    return ZoraKernel(doc, validate=planner_validation(doc.scene) if planner_check else None)


def run(payload: dict[str, Any]) -> dict[str, Any]:
    doc = ZoraDoc.model_validate(payload["doc"])
    kernel = kernel_for(doc, planner_check=bool(payload.get("planner_check", True)))
    allowed = payload.get("allowed_ops")
    result = kernel.apply(payload.get("ops") or [], by=str(payload.get("by") or "conductor"),
                          allowed_ops=tuple(allowed) if allowed is not None else None)
    return {"applied": result.applied, "rejected": result.rejected, "staged": result.staged,
            "changes": [asdict(c) for c in result.changes], "plan": kernel.export(),
            "person": kernel.person().model_dump()}
