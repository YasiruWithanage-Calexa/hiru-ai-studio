"""Every test, wherever it lives: the stored-file cache (plan/2026-11-21) is a fresh folder per test, never the
developer's own (`%LOCALAPPDATA%/hiru-ai/files`), so no test reads another's bytes or leaves files behind."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _own_file_cache(monkeypatch: Any, tmp_path: Path) -> Iterator[None]:
    from hiru_ai.core import file_store

    monkeypatch.setenv("FILES__CACHE_DIR", str(tmp_path / "file-cache"))
    file_store.MEMORY.clear()
    yield
    file_store.MEMORY.clear()
