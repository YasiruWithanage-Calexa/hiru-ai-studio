"""A small in-process TTL cache with request coalescing (single flight).

Concurrent misses for the same key share one load instead of each hitting the database, so a page
that fires eight API calls at once reads a profile once, not eight times. `None` results are not
cached: a row that does not exist yet (a profile created a moment later) is looked up again.

Per process only. With several API instances, a change made on one instance reaches the others
when the entry expires, so keep TTLs short and call `invalidate` where this process writes.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable


class AsyncTTLCache[T]:
    def __init__(self, ttl_s: float, max_entries: int = 1024) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._values: dict[Hashable, tuple[float, T]] = {}
        self._inflight: dict[Hashable, asyncio.Future[T | None]] = {}

    async def get(self, key: Hashable, load: Callable[[], Awaitable[T | None]]) -> T | None:
        hit = self._values.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future[T | None] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await load()
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved: waiters re-raise it, nobody else needs to
            raise
        else:
            if value is not None:
                if len(self._values) >= self._max:
                    self._values.clear()
                self._values[key] = (time.monotonic() + self._ttl, value)
            future.set_result(value)
            return value
        finally:
            self._inflight.pop(key, None)

    def invalidate(self, key: Hashable) -> None:
        self._values.pop(key, None)

    def clear(self) -> None:
        self._values.clear()
