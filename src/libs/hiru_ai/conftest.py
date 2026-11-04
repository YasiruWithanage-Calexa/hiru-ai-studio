"""Tests that live with a part (ADR 0006) never reach a real model, whatever the developer's `.env` holds."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import no_real_models


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch: Any) -> Iterator[None]:
    no_real_models(monkeypatch)
    yield
    get_settings.cache_clear()
