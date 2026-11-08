"""The status read (plan/2026-11-08c phase 3): cheap, ticket-free, and right about what is busy."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tests.api.conftest import World


def _get(world: World, who, since: str | None = None, production=None):  # type: ignore[no-untyped-def]
    pid = production or world.production
    params = {"since": since} if since else {}
    return world.client.get(f"/v1/productions/{pid}/live", params=params, headers=world.headers(who))


def _seed(world: World) -> None:
    pid = str(world.production)

    async def go() -> None:
        await world.repos.frames.create_many([  # type: ignore[attr-defined]
            {"id": "f1", "production_id": pid, "shot_id": "s1", "status": "running"},
            {"id": "f2", "production_id": pid, "shot_id": "s1", "status": "done", "storage_path": "p/f2.png"},
            {"id": "fx", "production_id": str(world.other_production), "shot_id": "s9", "status": "running"}])

    asyncio.run(go())


def test_idle_production_is_not_busy(world: World) -> None:
    body = _get(world, world.producer).json()
    assert body == {"busy": False, "version": None, "items": []}


def test_a_running_frame_makes_it_busy_and_only_this_production_counts(world: World) -> None:
    _seed(world)
    body = _get(world, world.producer).json()
    assert body["busy"] is True
    got = [(i["kind"], i["id"], i["shot_id"], i["status"]) for i in body["items"]]
    assert got == [("frame", "f1", "s1", "running")]


def test_finished_work_shows_once_after_since_then_busy_goes_false(world: World) -> None:
    _seed(world)
    first = _get(world, world.producer).json()
    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    world.repos.frames.rows["f1"].update(status="done", updated_at=later)  # type: ignore[attr-defined]
    after = _get(world, world.producer, since=first["version"]).json()
    assert after["busy"] is False
    assert [(i["id"], i["status"]) for i in after["items"]] == [("f1", "done")]
    assert _get(world, world.producer, since=after["version"]).json()["items"] == []


def test_it_costs_one_query_per_table_and_mints_no_ticket(world: World) -> None:
    _seed(world)
    r = _get(world, world.producer)
    repos = world.repos
    assert (repos.frames.live_queries, repos.renders.live_queries, repos.documents.live_queries,  # type: ignore[attr-defined]
            repos.jobs.live_queries) == (1, 1, 1, 1)  # type: ignore[attr-defined]
    assert "url" not in r.text and "ticket" not in r.text and "/files/" not in r.text


def test_running_job_is_listed_with_its_kind(world: World) -> None:
    async def go() -> None:
        await world.repos.jobs.create({"id": str(uuid4()), "kind": "shot_produce", "status": "running",  # type: ignore[attr-defined]
                                       "production_id": str(world.production)})

    asyncio.run(go())
    item = _get(world, world.writer).json()["items"][0]
    assert (item["kind"], item["job_kind"], item["shot_id"]) == ("job", "shot_produce", None)


def test_a_stranger_cannot_read_it(world: World) -> None:
    assert _get(world, world.outsider).status_code in (403, 404)
