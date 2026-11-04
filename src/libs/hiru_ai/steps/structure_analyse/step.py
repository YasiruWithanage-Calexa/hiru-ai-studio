"""structure_analyse: documents and canon in, a plan with questions out; the plan and answers in, a structure out.

    {"op": "analyse", "documents": [{id, filename, role, text}], "canon": [rows]}
    {"op": "default_answers", "questions": [...]}
    {"op": "apply_answers", "plan": {...}, "answers": {...}, "canon": [rows]}
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.structure_analyse import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "analyse":
        return {"plan": logic.analyse(payload["documents"], payload["canon"])}
    if op == "default_answers":
        return {"answers": logic.default_answers(payload["questions"])}
    if op == "apply_answers":
        return {"structure": logic.apply_answers(payload["plan"], payload["answers"], payload["canon"])}
    raise ValueError(f"unknown op {op!r}")
