"""The Shot Planner Jonathan function's HTTP contract (plan/2026-11-05e §4.4), the echo template's: 400 for a bad
payload, a
crash fails the job and answers 200, a transient network error answers 500 so Cloud Tasks retries."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "services" / "shot_planner_jonathan"))

from shot_planner_jonathan.app import handler
from shot_planner_jonathan.runtime.config import get_config

from contracts.jobs import DispatchPayload, JobKind


class Request:
    def __init__(self, body: Any) -> None:
        self.body = body

    def get_json(self, silent: bool = False) -> Any:
        return self.body


class FakeJobs:
    def __init__(self) -> None:
        self.failed: list[tuple[UUID, str]] = []

    def fail(self, job_id: UUID, error: str) -> None:
        self.failed.append((job_id, error))


def payload(production: bool = True) -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.PLAN_SCENE_JONATHAN, actor_user_id=uuid4(),
                           production_id=uuid4() if production else None, pipeline=[JobKind.PLAN_SCENE_JONATHAN])


def test_a_bad_payload_is_400_and_never_builds_the_jobs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handler, "build_jobs", lambda: pytest.fail("jobs built"))
    assert handler.handle(Request({"job_id": "nope"})) == ({"error": "bad payload"}, 400)
    assert handler.handle(Request(payload(production=False).model_dump(mode="json")))[1] == 400


def test_a_crash_fails_the_job_in_words_that_name_the_classic_planner_and_answers_200(monkeypatch: pytest.MonkeyPatch):
    jobs = FakeJobs()
    monkeypatch.setattr(handler, "build_jobs", lambda: jobs)
    monkeypatch.setattr(handler, "run_graph", lambda p, j: (_ for _ in ()).throw(RuntimeError("boom")))
    body, code = handler.handle(Request(payload().model_dump(mode="json")))
    assert (body, code) == ({"error": "failed"}, 200) and "classic planner" in jobs.failed[0][1]


def test_a_transient_network_error_answers_500_so_the_task_is_retried(monkeypatch: pytest.MonkeyPatch):
    jobs = FakeJobs()
    monkeypatch.setattr(handler, "build_jobs", lambda: jobs)
    monkeypatch.setattr(handler, "run_graph", lambda p, j: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert handler.handle(Request(payload().model_dump(mode="json"))) == ({"error": "retry"}, 500) and not jobs.failed


def test_a_good_delivery_hands_over_to_the_system_and_returns_its_result(monkeypatch: pytest.MonkeyPatch):
    seen: list[DispatchPayload] = []
    monkeypatch.setattr(handler, "build_jobs", lambda: FakeJobs())
    monkeypatch.setattr(handler, "run_graph", lambda p, j: seen.append(p) or {"scenes": 1})
    body, code = handler.handle(Request(payload().model_dump(mode="json")))
    assert (body, code) == ({"scenes": 1}, 200) and seen[0].kind is JobKind.PLAN_SCENE_JONATHAN


def test_the_function_builds_its_jobs_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPABASE__URL", "http://db.test")
    monkeypatch.setenv("API__INTERNAL_URL", "http://api.test/")
    get_config.cache_clear()
    try:
        jobs = handler.build_jobs()
        assert jobs.rest.rest == "http://db.test/rest/v1" and jobs.api == "http://api.test"
    finally:
        get_config.cache_clear()
