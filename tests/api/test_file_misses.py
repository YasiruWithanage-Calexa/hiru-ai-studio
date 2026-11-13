"""A file Supabase does not have is not asked for again for a while (plan/2026-11-13b phase 9)."""
from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from api.cache import job_ended
from api.services import file_cache


class _Resp:
    status_code = 404
    headers: ClassVar[dict[str, str]] = {}


class _Stream:
    async def __aenter__(self) -> _Resp:
        return _Resp()

    async def __aexit__(self, *_a: object) -> None:
        return None


class _Client:
    asked = 0

    def __init__(self, *_a: object, **_k: object) -> None: ...

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_a: object) -> None:
        return None

    def stream(self, *_a: object, **_k: object) -> _Stream:
        _Client.asked += 1
        return _Stream()


def test_a_404_is_remembered_until_the_path_is_stored_or_a_job_ends(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from api.config import get_settings

    settings = get_settings().model_copy(deep=True)
    settings.files.cache_dir = str(tmp_path)
    settings.files.cache_max_gb = 1
    monkeypatch.setattr(file_cache.httpx, "AsyncClient", _Client)
    file_cache.MISSES.clear()
    _Client.asked = 0
    cache = file_cache.FileCache(settings)

    async def ask() -> None:
        with pytest.raises(file_cache.NotFound):
            await cache.fetch("takes", "p/s/t.poster.webp")

    async def go() -> None:
        await ask()
        await ask()
        assert _Client.asked == 1
        file_cache.forget_missing("takes", "p/s/t.poster.webp")
        await ask()
        assert _Client.asked == 2
        job_ended()
        await ask()
        assert _Client.asked == 3

    asyncio.run(go())
