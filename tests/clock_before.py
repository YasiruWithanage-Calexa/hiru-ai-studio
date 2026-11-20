"""The clock before plan/2026-11-20 D1, for the tests that replay a plan recorded on it (run 3's gold, recorded Zora
scenes): on the measured clock some of their takes are a second short, and that is the truth arriving, not what those
tests are about. The measured clock is tested in tests/contracts/test_clock_cases.py and
tests/raphael/test_line_parts.py.
"""
from __future__ import annotations

from typing import Any


def clock_before_line_parts(monkeypatch: Any, *more: Any) -> None:
    """The clock before plan/2026-11-20 D1: lead-in 0.5 s, 0.3 s between lines, no pause at a sentence end inside a
    line. `more`: other modules that imported `LEAD_IN_S` / `TAIL_S` / `SENTENCE_PAUSE_S` by name (a planner's own)."""
    from contracts import shotplan, timing

    for module in (shotplan, *more):
        if hasattr(module, "LEAD_IN_S"):
            monkeypatch.setattr(module, "LEAD_IN_S", 0.5)
    monkeypatch.setattr(shotplan, "LINE_GAP_S", 0.3)
    for module in (timing, shotplan, *more):
        if hasattr(module, "SENTENCE_PAUSE_S"):
            monkeypatch.setattr(module, "SENTENCE_PAUSE_S", 0.0)
