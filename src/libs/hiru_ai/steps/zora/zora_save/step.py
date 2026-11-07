"""zora_save: `{"scene", "lines", "canon", "production", "stored", "plan", "mended"?, "problems"?, "measures"?,
"person"?, "old_ids", "handles"}` → `{"shots", "lines", "fields", "removed", "stored"}` (plan/2026-11-06e §4.7).

Deterministic, no model, no database. Writes Zora's edited plan through the PLANNER's own write path (reached by id), so
a shot comes out exactly as the planner would have stored it: its card, intent, finished camera design and current
pins; the lines rebound by code. Shots that were there before the turn keep their ids (`logic.keep_ids`). An approved
scene, or a plan the planner cannot read, comes back `{"refused": ...}` with the reason. The undo stack is
`logic.Stack`.

This file is the third, with `zora_kernel/step.py` and `zora_board/gate.py`, that names the planner's parts.
"""
from __future__ import annotations

from typing import Any

from hiru_ai.core import parts
from hiru_ai.steps.zora.zora_save import logic

WRITE = "jonathan_write"  # the planner whose stored plan Zora edits (tests/zora/test_removal.py)


def write_rows(scene: dict[str, Any], lines: list[Any], stored: dict[str, Any], canon: list[Any],
               production: dict[str, Any], *, job_id: str = "") -> dict[str, Any]:
    """The planner's write path on a stored plan, as it is: `{shots, lines, fields}` or `{refused}`."""
    out = parts.step(WRITE, "step").run({"scene": scene, "lines": lines, "stored": stored, "canon": canon,
                                         "production": production, "job_id": job_id})
    if "refused" in out or "malformed" in out:
        return {"refused": str(out.get("refused") or f"The plan could not be stored: {out.get('malformed')}")}
    return out


def run(payload: dict[str, Any]) -> dict[str, Any]:
    stored = logic.stored_after(dict(payload["stored"]), dict(payload["plan"]),
                                mended=list(payload.get("mended") or []), problems=list(payload.get("problems") or []),
                                measures=list(payload.get("measures") or []), person=dict(payload.get("person") or {}))
    out = write_rows(dict(payload["scene"]), list(payload.get("lines") or []), stored,
                     list(payload.get("canon") or []), dict(payload.get("production") or {}))
    if "refused" in out:
        return out
    shots, lines, removed = logic.keep_ids(out["shots"], out["lines"], [str(i) for i in payload.get("old_ids") or []],
                                           [str(h) for h in payload.get("handles") or []])
    return {"shots": shots, "lines": lines, "fields": out["fields"], "removed": removed, "stored": stored}
