"""Every Raphael test runs with no real model: an empty key beats the one in a developer's `.env` (CLAUDE.md "Tests
never
call OpenAI")."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.core.testing import no_real_models
from tests.clock_before import clock_before_line_parts


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch: Any) -> Iterator[None]:
    no_real_models(monkeypatch)
    monkeypatch.setenv("RAPHAEL_BREAKDOWN", "false")  # plan/2026-11-10: a test that wants the breakdown asks for it
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    yield



def run_3_clock(monkeypatch: Any) -> None:
    """The clock run 3 and pass 5 (the gold bins) were planned on, before plan/2026-11-20 D1: on the measured one two of
    run 3's clips (c07, c10) are a second short, which `finish` now refuses (D5)."""
    from contracts.raphael import checks
    from contracts.raphael import scene as rscene

    clock_before_line_parts(monkeypatch, rscene, checks)
