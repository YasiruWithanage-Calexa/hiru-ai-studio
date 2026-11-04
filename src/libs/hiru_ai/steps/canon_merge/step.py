"""canon_merge: `{"op": "combine", "rules": [candidates], "model": [candidates]}` and its siblings, JSON in, JSON out.

    {"op": "counts", "candidates": [...]}                       → speakers and places with their counts
    {"op": "from_answer", "entities": [...]}                    → candidates from the extractor's entities
    {"op": "combine", "rules": [...], "model": [...]}           → the merged candidates
    {"op": "dedupe_input", "candidates": [...]}                 → the deduper's input
    {"op": "apply_groups", "candidates": [...], "groups": [...]} → the candidates left after merging duplicates
"""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.canon_merge import logic


def run(payload: dict[str, Any]) -> dict[str, Any]:
    op = payload["op"]
    if op == "counts":
        return logic.counts(payload["candidates"])
    if op == "from_answer":
        return {"candidates": logic.from_answer(payload["entities"])}
    if op == "combine":
        return {"candidates": logic.combine(payload["rules"], payload["model"])}
    if op == "dedupe_input":
        return {"candidates": logic.dedupe_input(payload["candidates"])}
    if op == "apply_groups":
        return {"candidates": logic.apply_groups(payload["candidates"], payload["groups"])}
    raise ValueError(f"unknown op {op!r}")
