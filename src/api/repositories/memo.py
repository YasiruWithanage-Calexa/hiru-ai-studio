"""A read memo for one API request (plan/2026-11-13b phase 1).

A page open used to read the same scene, shots, lines and episode many times, because each loader (`production.load`,
`scenes.load`, `scenes.view`, `structure.get_episode`) fetched them on its own. While a request is open
(`open_memo`, called by `RequestLogMiddleware`), the idempotent getters named in `MEMOISED` run once per distinct
arguments; later and concurrent callers get a copy of the same answer.

Rules:
- **Any call that is not a known read, on any repository, clears the memo** (before and after it runs), so a write
  followed by a read in one request always sees the write. A method name that is not recognised as a read counts as
  a write: the failure mode is a redundant query, never a stale row.
- A read that began before a write never stores its answer (generation counter).
- Callers get a deep copy, so a router may edit a row without changing what the next caller sees.
- Outside a request (workers, scripts, tests that call repositories directly) there is no memo: nothing changes.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

# repo attribute on `Repos` -> the getters whose answer may be shared inside one request.
MEMOISED: dict[str, frozenset[str]] = {
    "scenes": frozenset({"get", "list", "list_light"}),
    "shots": frozenset({"get", "list"}),
    "lines": frozenset({"list"}),
    "episodes": frozenset({"get", "list"}),
    "scene_looks": frozenset({"list"}),
    "looks": frozenset({"list_for_production"}),
    "canon": frozenset({"list"}),
}

# A method whose name starts like this reads and changes nothing (it neither clears nor is kept).
_READ_PREFIXES = ("get", "list", "latest", "counts", "live", "active", "role_of", "open_count", "count", "search",
                  "tokens_since", "budget", "prices", "scene_usage", "unassigned_usage", "recent_usage",
                  "lines_by_scene", "versions", "threads", "thread")


@dataclass
class _Memo:
    generation: int = 0
    done: dict[Any, Any] = field(default_factory=dict)
    inflight: dict[Any, asyncio.Future[Any]] = field(default_factory=dict)

    def clear(self) -> None:
        self.generation += 1
        self.done.clear()
        self.inflight.clear()


_memo: ContextVar[_Memo | None] = ContextVar("api_read_memo", default=None)


def open_memo() -> Any:
    """Start a memo for the current request; returns the token for `close_memo`."""
    return _memo.set(_Memo())


def close_memo(token: Any) -> None:
    _memo.reset(token)


def forget() -> None:
    """Drop everything remembered in this request (a write happened that the repositories could not see)."""
    memo = _memo.get()
    if memo is not None:
        memo.clear()


class MemoRepo:
    """Wraps one repository: memoises its listed getters, clears the memo on anything that might write."""

    def __init__(self, inner: Any, name: str) -> None:
        self._inner = inner
        self._name = name
        self._reads = MEMOISED.get(name, frozenset())

    def __getattr__(self, attr: str) -> Any:
        target = getattr(self._inner, attr)
        if attr.startswith("_") or not callable(target):
            return target
        if attr in self._reads:
            return self._memoised(attr, target)
        if attr.startswith(_READ_PREFIXES):
            return target
        return self._clearing(target)

    def _memoised(self, attr: str, target: Any) -> Any:
        key_head = (self._name, attr)

        async def call(*args: Any, **kwargs: Any) -> Any:
            memo = _memo.get()
            if memo is None:
                return await target(*args, **kwargs)
            key = (*key_head, args, tuple(sorted(kwargs.items())))
            try:
                hash(key)
            except TypeError:
                return await target(*args, **kwargs)
            if key in memo.done:
                return copy.deepcopy(memo.done[key])
            waiting = memo.inflight.get(key)
            if waiting is not None:
                return copy.deepcopy(await asyncio.shield(waiting))
            generation = memo.generation
            future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            memo.inflight[key] = future
            try:
                result = await target(*args, **kwargs)
            except BaseException as exc:
                if memo.inflight.get(key) is future:
                    del memo.inflight[key]
                if not future.done():
                    future.set_exception(exc if isinstance(exc, Exception) else RuntimeError("read cancelled"))
                    future.exception()  # mark retrieved: nobody may be waiting
                raise
            if memo.generation == generation:
                memo.done[key] = result
                memo.inflight.pop(key, None)
            if not future.done():
                future.set_result(result)
            return copy.deepcopy(result)

        return call

    def _clearing(self, target: Any) -> Any:
        async def call(*args: Any, **kwargs: Any) -> Any:
            forget()
            try:
                out = target(*args, **kwargs)
                return await out if inspect.isawaitable(out) else out
            finally:
                forget()

        return call


def wrap(repos: dict[str, Any]) -> dict[str, Any]:
    """`{name: repository}` with each repository wrapped."""
    return {name: MemoRepo(repo, name) for name, repo in repos.items()}
