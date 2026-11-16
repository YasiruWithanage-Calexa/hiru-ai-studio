"""Every parity test runs with no real model and none of a developer's switches (CLAUDE.md "Tests never call OpenAI"):
the engines are compared as the recordings were made, not as a `.env` sets `BREAKDOWN__ENABLED` or `READER__ENABLED`."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.core.testing import no_real_models


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch: Any) -> Iterator[None]:
    no_real_models(monkeypatch)
    monkeypatch.setenv("READER__ENABLED", "false")  # the recordings were made with the document reader off
    yield
