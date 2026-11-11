"""Every Raphael test runs with no real model: an empty key beats the one in a developer's `.env` (CLAUDE.md "Tests
never
call OpenAI")."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.core.testing import no_real_models


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch: Any) -> Iterator[None]:
    no_real_models(monkeypatch)
    monkeypatch.setenv("RAPHAEL_BREAKDOWN", "false")  # plan/2026-11-10: a test that wants the breakdown asks for it
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    yield
