"""The breakdown_canon_refine system's state. Plain data only (JSON-able)."""

from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    has_breakdown: bool  # without one, the looks alone are drafted from today's tables (D4)
    failed: str  # why nothing was written (the canon is as it was)
    report: dict[str, Any]  # the write's counts and the review list
