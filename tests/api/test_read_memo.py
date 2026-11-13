"""The per-request read memo (plan/2026-11-13b phase 1)."""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from api.repositories.memo import MemoRepo, close_memo, open_memo


class _Scenes:
    def __init__(self) -> None:
        self.reads = 0
        self.row: dict[str, Any] = {"id": "s1", "script": [{"a": 1}]}

    async def get(self, production_id: Any, scene_id: Any) -> dict[str, Any] | None:
        self.reads += 1
        await asyncio.sleep(0)
        return dict(self.row, script=list(self.row["script"]))

    async def update(self, scene_id: Any, fields: dict[str, Any]) -> dict[str, Any]:
        self.row.update(fields)
        return self.row


class _Frames:
    async def list_for_shots(self, ids: list[str]) -> list[dict[str, Any]]:
        return []

    async def create_many(self, rows: list[dict[str, Any]]) -> None:
        return None


def test_same_read_runs_once_and_returns_copies() -> None:
    async def go() -> None:
        inner = _Scenes()
        repo: Any = MemoRepo(inner, "scenes")
        token = open_memo()
        try:
            p, s = uuid4(), uuid4()
            a = await repo.get(p, s)
            a["script"].append("edited")  # a caller may edit its copy
            b = await repo.get(p, s)
            assert b["script"] == [{"a": 1}]
            assert inner.reads == 1
        finally:
            close_memo(token)

    asyncio.run(go())


def test_concurrent_reads_share_one_query() -> None:
    async def go() -> None:
        inner = _Scenes()
        repo: Any = MemoRepo(inner, "scenes")
        token = open_memo()
        try:
            p, s = uuid4(), uuid4()
            await asyncio.gather(repo.get(p, s), repo.get(p, s), repo.get(p, s))
            assert inner.reads == 1
        finally:
            close_memo(token)

    asyncio.run(go())


def test_a_write_through_any_repo_clears() -> None:
    async def go() -> None:
        scenes = _Scenes()
        repo: Any = MemoRepo(scenes, "scenes")
        frames: Any = MemoRepo(_Frames(), "frames")
        token = open_memo()
        try:
            p, s = uuid4(), uuid4()
            await repo.get(p, s)
            await frames.list_for_shots([])  # a read elsewhere keeps the memo
            await repo.get(p, s)
            assert scenes.reads == 1
            await repo.update(s, {"title": "x"})
            assert (await repo.get(p, s))["title"] == "x"
            assert scenes.reads == 2
            await frames.create_many([])  # a write on another repository clears too
            await repo.get(p, s)
            assert scenes.reads == 3
        finally:
            close_memo(token)

    asyncio.run(go())


def test_no_memo_outside_a_request() -> None:
    async def go() -> None:
        inner = _Scenes()
        repo: Any = MemoRepo(inner, "scenes")
        p, s = uuid4(), uuid4()
        await repo.get(p, s)
        await repo.get(p, s)
        assert inner.reads == 2

    asyncio.run(go())


def test_a_read_that_began_before_a_write_is_not_kept() -> None:
    async def go() -> None:
        inner = _Scenes()
        repo: Any = MemoRepo(inner, "scenes")
        token = open_memo()
        try:
            p, s = uuid4(), uuid4()
            slow = asyncio.ensure_future(repo.get(p, s))
            await asyncio.sleep(0)  # the read is in flight
            await repo.update(s, {"title": "new"})
            await slow
            assert (await repo.get(p, s))["title"] == "new"
            assert inner.reads == 2
        finally:
            close_memo(token)

    asyncio.run(go())
