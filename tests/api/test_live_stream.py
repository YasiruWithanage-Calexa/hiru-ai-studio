"""The pushed status stream (plan/2026-11-13d phase 5). A fake change source stands in for Supabase Realtime: tests
never touch the network."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from api.live.hub import CLOSE, Change, LiveHub
from contracts.live import LiveItem, LiveNotice
from tests.api.conftest import World

P = "00000000-0000-0000-0000-0000000000a1"
OTHER = "00000000-0000-0000-0000-0000000000a2"
now = datetime.now(UTC).isoformat()


class FakeSource:
    def __init__(self, script: list[tuple[float, str, str, dict[str, Any]]] | None = None) -> None:
        self.on_change: Change | None = None
        self.started = self.stopped = 0
        self.script = script or []

    async def start(self, on_change: Change) -> None:
        self.on_change, self.started = on_change, self.started + 1
        loop = asyncio.get_running_loop()
        for delay, table, event, record in self.script:  # changes that arrive while the stream is open
            loop.call_later(delay, lambda t=table, e=event, r=record: asyncio.ensure_future(on_change(t, e, r, now)))

    async def stop(self) -> None:
        self.stopped += 1


class Jobs:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows, self.reads = rows, 0

    async def get(self, job_id: UUID) -> dict[str, Any] | None:
        self.reads += 1
        return self.rows.get(str(job_id))


class Repos:
    def __init__(self, jobs: dict[str, dict[str, Any]] | None = None) -> None:
        self.jobs = Jobs(jobs or {})


def _hub(source: FakeSource, repos: Any = None, **kw: Any) -> LiveHub:
    return LiveHub(lambda: source, repos or Repos(), **kw)


def _drain(q: asyncio.Queue[Any]) -> list[Any]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_the_hub_listens_only_while_a_stream_is_open_and_sends_only_its_production() -> None:
    async def go() -> None:
        source = FakeSource()
        hub = _hub(source)
        assert not hub.listening
        sub = await hub.open(UUID(P), uuid4())
        assert hub.listening and source.started == 1
        assert source.on_change is not None
        row = {"id": "f1", "production_id": P, "shot_id": "s1", "status": "done", "updated_at": now,
               "prompt": "never sent"}
        await source.on_change("first_frames", "UPDATE", row, now)
        await source.on_change("first_frames", "UPDATE", {"id": "f9", "production_id": OTHER, "status": "done",
                                                          "updated_at": now}, now)
        got = _drain(sub.queue)
        assert [(m.kind, m.id, m.status) for m in got] == [("frame", "f1", "done")]
        assert "prompt" not in got[0].model_dump()  # a row is never forwarded, only the item's fields
        await hub.close(sub)
        assert not hub.listening and source.stopped == 1

    asyncio.run(go())


def test_a_build_event_carries_its_number_and_a_job_is_looked_up_once() -> None:
    async def go() -> None:
        source = FakeSource()
        first = str(UUID(int=1))
        jobs = {first: {"id": first, "production_id": P, "kind": "structure_build", "status": "running"}}
        repos = Repos(jobs)
        hub = _hub(source, repos)
        sub = await hub.open(UUID(P), uuid4())
        assert source.on_change is not None
        for seq in (4, 5):  # a job the hub has not seen: read once, then remembered
            await source.on_change("job_events", "INSERT", {"seq": seq, "job_id": first, "created_at": now}, now)
        assert repos.jobs.reads == 1
        assert [m.seq for m in _drain(sub.queue)] == [4, 5]
        jid = str(UUID(int=7))
        jobs[jid] = {"id": jid, "production_id": P, "kind": "structure_build", "status": "running"}
        await source.on_change("job_events", "INSERT", {"seq": 9, "job_id": jid, "created_at": now}, now)
        await source.on_change("job_events", "INSERT", {"seq": 10, "job_id": jid, "created_at": now}, now)
        got = _drain(sub.queue)
        assert [(m.id, m.job_kind, m.seq) for m in got] == [(jid, "structure_build", 9), (jid, "structure_build", 10)]
        assert repos.jobs.reads == 2
        # the job's own row then says done, with the number it has reached
        await source.on_change("jobs", "UPDATE", {"id": jid, "production_id": P, "kind": "structure_build",
                                                  "status": "done", "updated_at": now}, now)
        assert [(m.status, m.seq) for m in _drain(sub.queue)] == [("done", 10)]
        # another job's events are not the build page's business
        other = str(UUID(int=8))
        await source.on_change("jobs", "UPDATE", {"id": other, "production_id": P, "kind": "shot_produce",
                                                  "status": "running", "updated_at": now}, now)
        _drain(sub.queue)
        await source.on_change("job_events", "INSERT", {"seq": 11, "job_id": other, "created_at": now}, now)
        assert _drain(sub.queue) == []

    asyncio.run(go())


def test_a_persons_own_chat_message_is_not_sent_back_to_them() -> None:
    async def go() -> None:
        source = FakeSource()
        hub = _hub(source)
        me, them = uuid4(), uuid4()
        mine, theirs = await hub.open(UUID(P), me), await hub.open(UUID(P), them)
        assert source.on_change is not None
        await source.on_change("chat_messages", "INSERT", {"id": "m1", "production_id": P, "thread_id": "t1",
                                                           "author_user_id": str(me), "text": "never sent"}, now)
        assert _drain(mine.queue) == []
        got = _drain(theirs.queue)
        assert [(m.kind, m.id) for m in got] == [("thread", "t1")] and isinstance(got[0], LiveNotice)
        assert "text" not in got[0].model_dump()

    asyncio.run(go())


def test_a_fourth_tab_closes_the_oldest_and_a_slow_one_is_closed() -> None:
    async def go() -> None:
        source = FakeSource()
        hub = _hub(source, queue=3)
        me = uuid4()
        subs = [await hub.open(UUID(P), me) for _ in range(3)]
        await asyncio.sleep(0)
        fourth = await hub.open(UUID(P), me)
        assert _drain(subs[0].queue) == [CLOSE] and subs[1].queue.empty() and fourth.queue.empty()
        for n in range(5):
            hub.deliver(P, LiveItem(kind="frame", id=f"f{n}", status="running", updated_at=datetime.now(UTC)))
        assert fourth.overflowed and _drain(fourth.queue)[-1] is CLOSE

    asyncio.run(go())


# ── the route ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.config import get_settings

    for k, v in {"LIVE__TRANSPORT": "stream", "LIVE__IDLE_S": "0.4", "LIVE__MAX_S": "5",
                 "LIVE__KEEPALIVE_S": "0.1"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _events(body: str) -> list[tuple[str, dict[str, Any], str]]:
    out = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"]), lines.get("id", "")))
    return out


def test_with_polling_the_stream_is_404(world: World) -> None:
    r = world.client.get(f"/v1/productions/{world.production}/stream", headers=world.headers(world.producer))
    assert r.status_code == 404


def test_a_stranger_gets_404_and_nothing_opens(world: World, streaming: None) -> None:
    source = FakeSource()
    world.client.app.state.live_hub = _hub(source, world.repos)  # type: ignore[attr-defined]
    r = world.client.get(f"/v1/productions/{world.production}/stream", headers=world.headers(world.outsider))
    assert r.status_code == 404 and source.started == 0


def test_catch_up_then_each_change_once_then_it_ends_when_idle(world: World, streaming: None) -> None:
    pid = str(world.production)

    async def seed() -> None:
        await world.repos.frames.create_many([  # type: ignore[attr-defined]
            {"id": "f1", "production_id": pid, "shot_id": "s1", "status": "running"}])

    asyncio.run(seed())
    later = (datetime.now(UTC) + timedelta(seconds=2)).isoformat()
    source = FakeSource([
        (0.05, "first_frames", "UPDATE", {"id": "f1", "production_id": pid, "shot_id": "s1", "status": "running",
                                          "updated_at": now}),  # the same moment as the catch-up: sent once
        (0.1, "first_frames", "UPDATE", {"id": "fx", "production_id": str(world.other_production),
                                         "status": "done", "updated_at": later}),  # another production: never
        (0.15, "first_frames", "UPDATE", {"id": "f1", "production_id": pid, "shot_id": "s1", "status": "done",
                                          "updated_at": later}),
    ])
    hub = _hub(source, world.repos)
    world.client.app.state.live_hub = hub  # type: ignore[attr-defined]
    r = world.client.get(f"/v1/productions/{pid}/stream", headers=world.headers(world.producer))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = _events(r.text)
    assert [(e, d["id"], d["status"]) for e, d, _ in got] == [("item", "f1", "running"), ("item", "f1", "done")]
    assert got[-1][2] == datetime.fromisoformat(later).isoformat()  # the version to reconnect from
    assert ": keep-alive" in r.text
    assert not hub.listening and source.stopped == 1  # the last stream closed: the hub stops listening
