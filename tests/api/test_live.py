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
            {"id": "f2", "production_id": pid, "shot_id": "s1", "status": "done", "storage_path": "p/f2.png",
             "updated_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},  # finished long ago
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


def _build(world: World, status: str = "running", events: int = 3) -> str:
    job_id = str(uuid4())

    async def go() -> None:
        await world.repos.jobs.create({"id": job_id, "kind": "structure_build", "status": status,  # type: ignore[attr-defined]
                                       "production_id": str(world.production)})

    asyncio.run(go())
    for n in range(events):
        world.repos.jobs.add_event(job_id, "agent_step", {"text": f"step {n}"}, agent="ingestion")  # type: ignore[attr-defined]
    return job_id


def test_the_build_job_carries_its_newest_event_number(world: World) -> None:
    """plan/2026-11-13d phase 2: the build page asks for the events after its own last one only when this moves."""
    job_id = _build(world, events=3)
    item = next(i for i in _get(world, world.producer).json()["items"] if i["id"] == job_id)
    assert (item["job_kind"], item["seq"]) == ("structure_build", 3)
    world.repos.jobs.add_event(job_id, "stage", {"stage": "canon", "state": "active"})  # type: ignore[attr-defined]
    item = next(i for i in _get(world, world.producer).json()["items"] if i["id"] == job_id)
    assert item["seq"] == 4


def test_only_the_build_reads_an_event_number(world: World) -> None:
    async def go() -> None:
        await world.repos.jobs.create({"id": str(uuid4()), "kind": "shot_produce", "status": "running",  # type: ignore[attr-defined]
                                       "production_id": str(world.production)})

    asyncio.run(go())
    item = _get(world, world.writer).json()["items"][0]
    assert item["seq"] is None
    assert world.repos.jobs.seq_queries == 0  # type: ignore[attr-defined]
    _build(world, events=0)
    items = _get(world, world.writer).json()["items"]
    assert world.repos.jobs.seq_queries == 1  # type: ignore[attr-defined]
    assert next(i for i in items if i["job_kind"] == "structure_build")["seq"] is None  # no event yet


def test_with_schema_v25_it_is_one_query(world: World) -> None:
    """plan/2026-11-13d phase 3: `live_items()` answers for the four tables and the build's event number at once."""
    now = datetime.now(UTC).isoformat()
    calls: list[tuple[str, object]] = []

    async def one_query(production_id, since):  # type: ignore[no-untyped-def]
        calls.append((str(production_id), since))
        return [{"kind": "frame", "id": "f1", "shot_id": "s1", "status": "running", "job_kind": None,
                 "updated_at": now, "seq": None},
                {"kind": "job", "id": str(uuid4()), "shot_id": None, "status": "running",
                 "job_kind": "structure_build", "updated_at": now, "seq": 7}]

    world.repos.jobs.live_items_from = one_query  # type: ignore[attr-defined]
    body = _get(world, world.producer).json()
    assert [(i["kind"], i["status"], i["seq"]) for i in body["items"]] == [("frame", "running", None),
                                                                          ("job", "running", 7)]
    assert body["busy"] is True and len(calls) == 1
    repos = world.repos
    assert (repos.frames.live_queries, repos.renders.live_queries, repos.documents.live_queries,  # type: ignore[attr-defined]
            repos.jobs.live_queries, repos.jobs.seq_queries) == (0, 0, 0, 0, 0)  # type: ignore[attr-defined]
