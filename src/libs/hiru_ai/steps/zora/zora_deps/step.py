"""zora_deps: `{"doc", "ops", "by"?, "lane"?, "forced"?}` → `{"tasks", "rewritten", "removed", "stale", "joins",
"end_touched", "offer", "plan"}` (plan/2026-11-06e §4.3).

Deterministic, no model. Applies the ops with the kernel (reached by id), then reads which parts of the plan went stale:
the author tasks (each with the effects it must deliver and its scope, as shot numbers AFTER the ops), the shots whose
frame and prompt are out of date, and `offer`: why the edit is too big to be one ("" when it is not). Handles never
leave the step; numbers do. The rules are `logic`.
"""
from __future__ import annotations

from typing import Any

from contracts.zora.doc import ZoraDoc
from hiru_ai.core import parts
from hiru_ai.steps.zora.zora_deps.logic import plan_tasks, recut_guard


def run(payload: dict[str, Any]) -> dict[str, Any]:
    doc = ZoraDoc.model_validate(payload["doc"])
    kernel = parts.step("zora_kernel", "step").kernel_for(doc, planner_check=False)
    before = len(doc.shots)
    result = kernel.apply(payload.get("ops") or [], by=str(payload.get("by") or "conductor"))
    stale = plan_tasks(kernel, result.changes)

    def numbers(handles: Any) -> list[int]:
        return sorted(n for h in handles if (n := kernel.number_of(h)) is not None)

    offer = recut_guard(str(payload.get("lane") or "edit"), str(payload.get("forced") or ""), before, stale)
    return {"tasks": [{**t.data(), "scope": numbers(t.scope)} for t in stale.tasks],
            "rewritten": numbers(stale.rewritten), "removed": len(stale.removed), "stale": numbers(stale.stale),
            "joins": numbers(stale.joins), "end_touched": stale.end_touched, "offer": offer,
            "rejected": result.rejected, "plan": kernel.export()}
