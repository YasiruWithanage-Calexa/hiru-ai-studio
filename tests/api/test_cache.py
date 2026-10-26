"""AsyncTTLCache: concurrent misses share one load; misses (None) and failures are not cached."""
from __future__ import annotations

import asyncio

import pytest

from api.cache import AsyncTTLCache


async def test_concurrent_misses_share_one_load() -> None:
    cache: AsyncTTLCache[dict[str, int]] = AsyncTTLCache(30)
    calls = 0

    async def load() -> dict[str, int]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"v": 1}

    results = await asyncio.gather(*[cache.get("k", load) for _ in range(8)])
    assert calls == 1
    assert all(r == {"v": 1} for r in results)
    await cache.get("k", load)
    assert calls == 1  # served from cache


async def test_none_is_not_cached_and_invalidate_reloads() -> None:
    cache: AsyncTTLCache[int] = AsyncTTLCache(30)
    values = iter([None, 1, 2])

    async def load() -> int | None:
        return next(values)

    assert await cache.get("k", load) is None
    assert await cache.get("k", load) == 1
    cache.invalidate("k")
    assert await cache.get("k", load) == 2


async def test_failure_reaches_every_waiter_and_is_not_cached() -> None:
    cache: AsyncTTLCache[int] = AsyncTTLCache(30)

    async def boom() -> int:
        await asyncio.sleep(0.01)
        raise RuntimeError("db down")

    results = await asyncio.gather(*[cache.get("k", boom) for _ in range(3)], return_exceptions=True)
    assert all(isinstance(r, RuntimeError) for r in results)

    async def ok() -> int:
        return 5

    assert await cache.get("k", ok) == 5


async def test_expired_entry_reloads() -> None:
    cache: AsyncTTLCache[int] = AsyncTTLCache(0)
    n = 0

    async def load() -> int:
        nonlocal n
        n += 1
        return n

    assert await cache.get("k", load) == 1
    assert await cache.get("k", load) == 2


@pytest.mark.parametrize("ttl", [30])
async def test_entries_are_bounded(ttl: int) -> None:
    cache: AsyncTTLCache[int] = AsyncTTLCache(ttl, max_entries=2)

    async def one() -> int:
        return 1

    for key in "abc":
        await cache.get(key, one)
    assert len(cache._values) <= 2
