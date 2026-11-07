"""The HTTP contract of the function: one job per press, its renders in parallel, idempotent per job_id."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from video_render.app import handler
from video_render.engine import render

from contracts.jobs import DispatchPayload, JobKind
from tests.services.fakes import FakeJobs
from tests.services.video_render.conftest import PID, USER, FakeStore, config, make_spec, ref, render_row


def payload(*render_ids: str, **kw: Any) -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.VIDEO_RENDER, actor_user_id=USER, production_id=PID,
                           pipeline=[JobKind.VIDEO_RENDER], state={"render_ids": list(render_ids)}, **kw)


class Req:
    def __init__(self, body: dict | None) -> None:
        self.body = body

    def get_json(self, silent: bool = True) -> dict | None:
        return self.body


def test_a_press_with_three_takes_makes_three_takes_and_closes_the_job():
    rows = [render_row() for _ in range(3)]
    store, jobs = FakeStore(*rows), FakeJobs()
    result = handler.run(payload(*[r["id"] for r in rows]), store, jobs, config())  # type: ignore[arg-type]
    assert result == {"done": 3, "failed": 0, "refused": 0, "skipped": 0}
    assert jobs.status == "done" and jobs.fields["result"] == result
    assert len(store.takes) == 3 and len({t["id"] for t in store.takes}) == 3
    assert [e["status"] for e in jobs.events if e["type"] == "progress"] == ["done"] * 3
    assert store.audits[0]["action"] == "take.render" and store.audits[0]["actor_agent"] == "video_render"


def test_one_failed_take_does_not_stop_the_others():
    bad = render_row(make_spec([ref("the character sheet for Nimal", "elsewhere/x.png")]))
    good = render_row()
    store, jobs = FakeStore(bad, good), FakeJobs()
    result = handler.run(payload(bad["id"], good["id"]), store, jobs, config())  # type: ignore[arg-type]
    assert result["done"] == 1 and result["failed"] == 1
    assert jobs.status == "done"  # the job ran; the failed take is on its own row
    assert [e["type"] for e in jobs.events if e.get("status") == "failed"] == ["warning"]


def test_a_finished_job_is_skipped_on_redelivery():
    row = render_row()
    store = FakeStore(row)
    result = handler.run(payload(row["id"]), store, FakeJobs(status="done"), config())  # type: ignore[arg-type]
    assert result == {"skipped": "done"} and store.takes == []


def test_the_same_job_delivered_twice_makes_one_video():
    row = render_row()
    store, jobs = FakeStore(row), FakeJobs()
    p = payload(row["id"])
    handler.run(p, store, jobs, config())  # type: ignore[arg-type]
    jobs.status = "pending"  # a courier that never saw the first answer
    again = handler.run(p, store, jobs, config())  # type: ignore[arg-type]
    assert again["skipped"] == 1 and len(store.takes) == 1


def test_a_crash_inside_a_render_marks_that_render_failed(monkeypatch):
    row = render_row()
    store = FakeStore(row)
    monkeypatch.setattr(render, "run_render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = handler.run(payload(row["id"]), store, FakeJobs(), config())  # type: ignore[arg-type]
    assert result["failed"] == 1 and store.rows[row["id"]]["error"] == render.FAILED


# ── the HTTP shell ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_bad_payload_is_400():
    assert handler.handle(Req({"nonsense": 1})) == ({"error": "bad payload"}, 400)
    assert handler.handle(Req(None))[1] == 400
    no_production = payload("x").model_dump(mode="json") | {"production_id": None}
    assert handler.handle(Req(no_production))[1] == 400


@pytest.fixture
def wired(monkeypatch):
    jobs = FakeJobs()
    monkeypatch.setattr(handler, "get_config", lambda: config())
    monkeypatch.setattr(handler, "Rest", lambda *a, **k: object())
    monkeypatch.setattr(handler, "Store", lambda rest: FakeStore())
    monkeypatch.setattr(handler, "Jobs", lambda *a, **k: jobs)
    jobs.fail = lambda job_id, error: jobs.fields.update(error=error)  # type: ignore[method-assign]
    return jobs


def test_a_transient_network_error_asks_for_a_retry(wired, monkeypatch):
    monkeypatch.setattr(handler, "run", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    body = payload("x").model_dump(mode="json")
    assert handler.handle(Req(body)) == ({"error": "retry"}, 500)


def test_any_other_crash_fails_the_job_and_answers_200(wired, monkeypatch):
    monkeypatch.setattr(handler, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    body = payload("x").model_dump(mode="json")
    assert handler.handle(Req(body)) == ({"error": "failed"}, 200)
    assert wired.fields["error"] == "Making the video failed."
