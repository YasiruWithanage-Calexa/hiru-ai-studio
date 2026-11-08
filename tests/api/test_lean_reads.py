"""Phase 4 of plan/2026-11-08c: access, canon and looks are kept briefly, and cleared when they must be."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from api.cache import job_ended
from api.deps import authz
from api.repositories.supabase import _PROMPT_COLUMNS, SupabaseCanon, SupabaseLooks
from tests.api.conftest import World
from tests.api.test_scenes import url


class _Query:
    """Just enough of the supabase query builder: every call chains, `execute` counts and answers."""

    def __init__(self, db: _Db, table: str) -> None:
        self.db, self.table = db, table

    def __getattr__(self, name: str) -> Any:
        if name == "execute":
            async def execute() -> Any:
                self.db.calls.append(self.table)
                return SimpleNamespace(data=[{"id": str(uuid4()), "code": "A"}])
            return execute
        return lambda *a, **k: self


class _Db:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def table(self, name: str) -> _Query:
        return _Query(self, name)


async def test_canon_is_read_once_per_window_and_again_after_a_write() -> None:
    db = _Db()
    canon, pid = SupabaseCanon(db), uuid4()  # type: ignore[arg-type]
    first = await canon.list(pid)
    first[0]["code"] = "edited by a caller"
    assert (await canon.list(pid))[0]["code"] == "A"  # a caller's edit does not reach the kept copy
    assert db.calls == ["canon_entities"]
    await canon.update(uuid4(), {"name": "x"})
    await canon.list(pid)
    assert db.calls == ["canon_entities", "canon_entities", "canon_entities"]


async def test_a_finished_job_clears_canon_and_looks() -> None:
    db = _Db()
    canon, looks, pid = SupabaseCanon(db), SupabaseLooks(db), uuid4()  # type: ignore[arg-type]
    await canon.list(pid)
    await looks.list_for_production(pid)
    await canon.list(pid)
    await looks.list_for_production(pid)
    assert db.calls == ["canon_entities", "canon_looks"]
    job_ended()
    await canon.list(pid)
    await looks.list_for_production(pid)
    assert db.calls == ["canon_entities", "canon_looks", "canon_entities", "canon_looks"]


def test_access_is_kept_and_a_role_change_through_the_api_is_seen_at_once(world: World) -> None:
    authz.forget_access()
    calls = 0
    real = world.repos.productions.get_with_role

    async def counting(*a: Any, **k: Any) -> Any:
        nonlocal calls
        calls += 1
        return await real(*a, **k)

    world.repos.productions.get_with_role = counting  # type: ignore[method-assign]
    h = world.headers(world.producer)
    for _ in range(3):
        assert world.client.get(url(world, "/access"), headers=h).status_code == 200
    assert calls == 1
    # Removing the person through the API takes effect on their very next request.
    gone = world.client.delete(url(world, f"/members/{world.producer}"), headers=world.headers(world.admin))
    assert gone.status_code == 204
    assert world.client.get(url(world, "/access"), headers=h).status_code == 404


def test_hot_prompt_read_leaves_out_the_ir() -> None:
    assert "ir" not in _PROMPT_COLUMNS.split(",")
    assert {"prose", "sections", "pins", "camera", "checks", "frame_id", "version"} <= set(_PROMPT_COLUMNS.split(","))
