"""Tests of the package never reach a real model, whatever the developer's `.env` holds."""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import no_real_models


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch: Any) -> Iterator[None]:
    no_real_models(monkeypatch)
    yield
    get_settings.cache_clear()


# The parity and adapter tests hold a part against the legacy service code it was ported from. Each function runs from
# its own folder in production, so each service folder goes on the path here, as scripts/lint_imports.py does.
for _service in sorted((Path(__file__).resolve().parents[2] / "src" / "services").iterdir()):
    if _service.is_dir() and not _service.name.startswith("_") and str(_service) not in sys.path:
        sys.path.insert(0, str(_service))
