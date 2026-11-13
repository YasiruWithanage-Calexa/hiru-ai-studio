"""Saving Zora's work in place on the shot rows, and the revisions behind undo (plan/2026-11-13 §3.5). The code lives
in `hiru_ai.core.coverage_rows` since phase 8 (Sable's change cards save the same way); this module names it for Zora's
turn and clicks.
"""
from __future__ import annotations

from hiru_ai.core.coverage_rows import (
    BEFORE_ROWS,
    CHANGED_MEANWHILE,
    CHANGES,
    KEPT,
    NO_UNDO,
    Plan,
    Saved,
    Saver,
    Stack,
    finish_designs,
    prune,
    revision,
    rows_for,
    rows_print,
)

__all__ = ["BEFORE_ROWS", "CHANGED_MEANWHILE", "CHANGES", "KEPT", "NO_UNDO", "Plan", "Saved", "Saver", "Stack",
           "finish_designs", "prune", "revision", "rows_for", "rows_print"]
