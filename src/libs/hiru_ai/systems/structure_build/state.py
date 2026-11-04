"""The structure_build system's state. The keys are the legacy graph's, so a checkpoint written by either engine can be
resumed by the other."""
from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    documents: list[dict[str, Any]]
    canon: list[dict[str, Any]]
    plan: dict[str, Any]
    answers: dict[str, dict[str, Any]]
    structure: dict[str, Any]
    report: dict[str, Any]
