"""The price list and the cross-production history are held briefly (plan/2026-11-13b phase 6)."""
from __future__ import annotations

import asyncio
from typing import Any

from api.repositories.supabase import SupabaseCosts


class _Query:
    def __init__(self, db: _Db, table: str) -> None:
        self.db, self.table = db, table

    def __getattr__(self, _name: str) -> Any:
        return lambda *a, **k: self

    async def execute(self) -> Any:
        self.db.calls.append(self.table)
        if self.db.fail:
            raise RuntimeError("down")
        rows = [{"id": 1}] if self.table == "prices" else [{"id": "u1", "phase": "frames"}]
        return type("R", (), {"data": rows})()


class _Db:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def table(self, name: str) -> _Query:
        return _Query(self, name)


def test_prices_are_read_once_and_a_new_price_clears_them() -> None:
    async def go() -> None:
        db = _Db()
        repo = SupabaseCosts(db)  # type: ignore[arg-type]
        a = await repo.prices()
        a.append({"edited": True})  # a caller's edit is not kept
        assert await repo.prices() == [{"id": 1}]
        assert db.calls.count("prices") == 1
        await repo.add_price({"kind": "tokens"})
        await repo.prices()
        assert db.calls.count("prices") == 3  # the insert, then a fresh read after it

    asyncio.run(go())


def test_a_failed_price_read_is_not_kept() -> None:
    async def go() -> None:
        db = _Db()
        db.fail = True
        repo = SupabaseCosts(db)  # type: ignore[arg-type]
        assert await repo.prices() == []
        db.fail = False
        assert await repo.prices() == [{"id": 1}]

    asyncio.run(go())


def test_only_the_cross_production_history_is_held() -> None:
    async def go() -> None:
        from uuid import uuid4

        db = _Db()
        repo = SupabaseCosts(db)  # type: ignore[arg-type]
        await repo.recent_usage(None, "frames", 400)
        await repo.recent_usage(None, "frames", 400)
        assert db.calls.count("token_usage") == 1
        mine = uuid4()
        await repo.recent_usage(mine, "frames", 400)
        await repo.recent_usage(mine, "frames", 400)
        assert db.calls.count("token_usage") == 3  # a production's own history is read each time

    asyncio.run(go())


def test_usage_sum_is_held_until_a_job_ends() -> None:
    from datetime import UTC, datetime

    from api.cache import job_ended
    from api.repositories.supabase import SupabaseUsage

    class Rpc:
        def __init__(self, db: Any) -> None:
            self.db = db

        async def execute(self) -> Any:
            self.db.sums += 1
            return type("R", (), {"data": 7})()

    class Db:
        sums = 0

        def rpc(self, *_a: Any, **_k: Any) -> Rpc:
            return Rpc(self)

    async def go() -> None:
        db = Db()
        repo = SupabaseUsage(db)  # type: ignore[arg-type]
        since = datetime(2026, 11, 1, tzinfo=UTC)
        assert await repo.tokens_since(since) == 7
        assert await repo.tokens_since(since) == 7
        assert db.sums == 1
        job_ended()
        await repo.tokens_since(since)
        assert db.sums == 2

    asyncio.run(go())
