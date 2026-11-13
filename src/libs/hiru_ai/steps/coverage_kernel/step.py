"""coverage_kernel: `{"scene", "shots", "lines", "characters"?, "ops", "by"?}` → `{"applied", "rejected", "notes",
"clips"}` (plan/2026-11-13 §3.2).

Deterministic, no model, no database. Reads the rows as coverage (`contracts.coverage`), applies the operations with
`logic.Kernel` and answers what landed, what was refused, and the clips after it as one head line each. Zora's turn uses
`logic.Kernel` directly (reached by id); this entry is for the CLI, the examples and the contract tests.
"""
from __future__ import annotations

from typing import Any

from contracts.coverage.scene import Coverage
from hiru_ai.steps.coverage_kernel.logic import Kernel


def run(payload: dict[str, Any]) -> dict[str, Any]:
    cov = Coverage.from_rows(dict(payload["scene"]), list(payload.get("shots") or []),
                             list(payload.get("lines") or []), list(payload.get("characters") or []))
    result = Kernel(cov).apply(list(payload.get("ops") or []), by=str(payload.get("by") or "conductor"))
    return {"applied": [{"by": a["by"], "text": a["text"]} for a in result.applied],
            "rejected": [{"op": r["op"], "reason": r["reason"]} for r in result.rejected], "notes": result.notes,
            "clips": [cov.clip_head(c) for c in cov.clips]}
