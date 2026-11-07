"""The canon_extract system's state. The keys are the legacy graph's, so a checkpoint written by either engine can be
resumed by the other (plan/2026-11-03 §9: finish or keep open jobs compatible)."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    documents: list[dict[str, str]]
    candidates: list[dict[str, Any]]
    notes: list[str]
    warnings: list[str]
    report: dict[str, Any]
    read: bool  # the candidates came from the document reader's readings: no model extraction or dedupe
