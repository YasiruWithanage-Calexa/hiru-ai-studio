"""The build page's poll answer (plan/2026-11-13d phase 3): `GET /build/events?after_seq=N`.

A delta applied to the view the caller holds must give the view `GET /build` draws from every event, at every point a
page could have read it. `apply` below is the rule the interface's `applyBuildDelta` follows (map-build.ts):
change both.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from api.routers.build import (
    STAGE_LABEL,
    AgentView,
    BuildDelta,
    BuildView,
    Summary,
    agent_status,
    fold,
    view,
)
from contracts.build import Stage
from contracts.jobs import JobStatus
from tests.api.conftest import World

SUMMARY = Summary(episodes=0, scenes=0, shots=0)


def _events() -> list[dict[str, Any]]:
    raw = [
        ("status", None, {"status": "running"}),
        ("stage", None, {"stage": "read", "state": "active", "text": ""}),
        ("agent_step", "ingestion", {"text": "Read 2 files."}),
        ("stage", None, {"stage": "read", "state": "done", "text": "2 documents"}),
        ("stage", None, {"stage": "canon", "state": "active"}),
        ("agent_step", "canon_extractor", {"text": "Found 4 characters.", "chips": ["Nimal", "Kumari"]}),
        ("warning", "canon_extractor", {"text": "Two spellings of Kumari."}),
        ("warning", "canon_extractor", {"text": "No age for Nimal."}),
        ("stage", None, {"stage": "canon", "state": "done", "text": "4 characters"}),
        ("stage", None, {"stage": "episodes", "state": "active", "text": "Splitting"}),
        ("progress", "script_architect", {"text": "Episode 1"}),
        ("question", "script_architect", {"text": "Two scene 4s: split them?"}),
        ("stage", None, {"stage": "nonsense", "state": "active"}),
        ("agent_step", "ingestion", {"text": "Read one more file."}),
        ("stage", None, {"stage": "episodes", "state": "done"}),
    ]
    return [{"seq": n + 10, "type": t, "agent": a, "payload": p, "created_at": f"2026-11-13T10:00:{n:02d}Z"}
            for n, (t, a, p) in enumerate(raw)]


def _delta(job: dict[str, Any], events: list[dict[str, Any]], after: int, open_q: int) -> BuildDelta:
    stages, agents, messages, last = fold(events)
    return BuildDelta(job_id=job["id"], status=JobStatus(job["status"]), error=job.get("error"), open_questions=open_q,
                      seq=max((e["seq"] for e in events), default=after), last_agent=last, stages=stages,
                      agents=agents, messages=messages)


def apply(held: BuildView, delta: BuildDelta) -> BuildView:
    """The interface's rule, in Python: what a page holding `held` draws after `delta`."""
    out = held.model_copy(deep=True)
    stages = {s.stage: s for s in out.stages}
    for c in delta.stages:
        stages[c.stage].state = c.state
        stages[c.stage].detail = c.text or stages[c.stage].detail
    agents = {a.agent: a for a in out.agents}
    for a in delta.agents:
        if a.agent in agents:
            agents[a.agent].detail = a.detail
        else:
            agents[a.agent] = AgentView(agent=a.agent, label=a.label, status="working", detail=a.detail)
    out.agents = list(agents.values())
    out.messages = [*out.messages, *(m for m in delta.messages if m.seq > held.seq)]
    out.last_agent = delta.last_agent or held.last_agent
    out.status, out.error, out.open_questions, out.seq = delta.status, delta.error, delta.open_questions, delta.seq
    for a in out.agents:
        a.status = agent_status(out.status, a.agent, out.last_agent)
    if out.status is JobStatus.DONE:
        stages[Stage.REVIEW].state = "active"
    return out


@pytest.mark.parametrize("final", ["running", "waiting_input", "done", "failed"])
def test_a_delta_on_any_earlier_view_gives_the_whole_view(final: str) -> None:
    events = _events()
    job = {"id": str(uuid4()), "status": final, "error": "boom" if final == "failed" else None}
    whole = view(job, events, 1, SUMMARY)
    for k in range(len(events) + 1):
        earlier = view({**job, "status": "running", "error": None}, events[:k], 0, SUMMARY)
        after = earlier.seq
        got = apply(earlier, _delta(job, events[k:], after, 1))
        assert got.model_dump() == whole.model_dump(), f"split at {k}"


def test_the_stage_labels_come_with_the_first_view() -> None:
    assert [s.label for s in view(None, [], 0, SUMMARY).stages] == [STAGE_LABEL[s] for s in Stage]


def _job(world: World, status: str = "running", n: int = 5) -> str:
    job_id = str(uuid4())

    async def go() -> None:
        await world.repos.jobs.create({"id": job_id, "kind": "structure_build", "status": status,  # type: ignore[attr-defined]
                                       "production_id": str(world.production)})

    asyncio.run(go())
    for e in _events()[:n]:
        world.repos.jobs.add_event(job_id, e["type"], e["payload"], agent=e["agent"])  # type: ignore[attr-defined]
    return job_id


def test_the_route_answers_only_what_is_new(world: World) -> None:
    job_id = _job(world, n=5)
    url = f"/v1/productions/{world.production}/build/events"
    first = world.client.get(url, headers=world.headers(world.writer)).json()
    assert (first["job_id"], first["status"], first["seq"]) == (job_id, "running", 5)
    assert [m["text"] for m in first["messages"]] == ["Read 2 files."]
    world.repos.jobs.add_event(job_id, "agent_step", {"text": "Found 4 characters."}, agent="canon_extractor")  # type: ignore[attr-defined]
    later = world.client.get(url, params={"after_seq": 5}, headers=world.headers(world.writer)).json()
    assert [m["text"] for m in later["messages"]] == ["Found 4 characters."]
    assert (later["seq"], later["last_agent"], later["stages"]) == (6, "canon_extractor", [])
    nothing = world.client.get(url, params={"after_seq": 6}, headers=world.headers(world.writer)).json()
    assert (nothing["seq"], nothing["messages"], nothing["agents"]) == (6, [], [])


def test_the_route_counts_the_open_questions_and_reads_no_rows_for_it(world: World) -> None:
    _job(world)
    world.repos.questions.add(production_id=str(world.production), status="open", key="k1", body="?")  # type: ignore[attr-defined]
    world.repos.questions.add(production_id=str(world.production), status="answered", key="k2", body="?")  # type: ignore[attr-defined]
    listed: list[int] = []
    original = world.repos.questions.list

    async def counting_list(*args: Any, **kwargs: Any) -> Any:
        listed.append(1)
        return await original(*args, **kwargs)

    world.repos.questions.list = counting_list  # type: ignore[method-assign]
    body = world.client.get(f"/v1/productions/{world.production}/build/events",
                            headers=world.headers(world.writer)).json()
    assert body["open_questions"] == 1
    full = world.client.get(f"/v1/productions/{world.production}/build", headers=world.headers(world.writer)).json()
    assert full["open_questions"] == 1
    assert listed == []  # both count; neither lists the questions


def test_without_a_build_it_says_so(world: World) -> None:
    body = world.client.get(f"/v1/productions/{world.production}/build/events", params={"after_seq": 3},
                            headers=world.headers(world.writer)).json()
    assert (body["job_id"], body["status"], body["seq"]) == (None, None, 3)


def test_a_stranger_gets_nothing(world: World) -> None:
    r = world.client.get(f"/v1/productions/{world.production}/build/events", headers=world.headers(world.outsider))
    assert r.status_code == 404


def test_the_summary_counts_rows_without_reading_them(world: World) -> None:
    pid = str(world.production)
    ep = world.repos.episodes.add(production_id=pid, number=1, title="E1", status="ready")  # type: ignore[attr-defined]
    for n in (1, 2):
        sc = world.repos.scenes.add(production_id=pid, episode_id=ep["id"], number=n)  # type: ignore[attr-defined]
        world.repos.shots.add(production_id=pid, scene_id=sc["id"], number=1)  # type: ignore[attr-defined]
    body = world.client.get(f"/v1/productions/{pid}/build", headers=world.headers(world.writer)).json()
    assert body["summary"] == {"episodes": 1, "scenes": 2, "shots": 2}
    assert world.repos.episodes.count_queries == 1  # type: ignore[attr-defined]
