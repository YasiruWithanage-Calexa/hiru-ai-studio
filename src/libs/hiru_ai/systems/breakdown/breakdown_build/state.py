"""The breakdown_build system's state. Plain data only (JSON-able)."""

from __future__ import annotations

from typing import Any, TypedDict


class State(TypedDict, total=False):
    uploads: list[dict[str, Any]]  # {document_id, filename, text, read_from} of each story document
    memory: dict[str, Any]  # the breakdown memory (contracts.breakdown.schema.Breakdown), dumped
    failed: str  # why there is no memory at all
    report: dict[str, Any]
