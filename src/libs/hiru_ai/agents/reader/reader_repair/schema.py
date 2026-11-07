"""Typed seams of the reader_repair agent: the document reader's own shapes (`contracts.doc_read`), so the service
engine and this agent send and read the same thing (plan/2026-11-06f §3)."""
from __future__ import annotations

from contracts.doc_read import PatchW as Output
from contracts.doc_read_run import RepairAsk as Input

__all__ = ["Input", "Output"]
