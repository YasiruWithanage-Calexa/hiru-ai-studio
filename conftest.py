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


def pytest_configure(config: Any) -> None:
    """The margins are installed before collection too: some test modules work out expected prices at import."""
    from api.margins import install

    install()


@pytest.fixture(autouse=True)
def _studio_margins() -> Iterator[None]:
    """Every test prices with the real margins file (plan/2026-11-23), as the API does after start-up; a test that
    installs its own gets the file's back afterwards."""
    from api.margins import install

    install()
    yield
    install()
