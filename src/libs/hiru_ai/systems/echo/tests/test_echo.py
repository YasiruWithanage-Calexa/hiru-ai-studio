"""The echo system against the legacy handler's lifecycle (tests/services/test_echo.py)."""
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeJobs
from hiru_ai.systems.echo import graph


def payload(message: str = "hi") -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.ECHO, actor_user_id=uuid4(), state={"message": message})


def ctx(jobs: FakeJobs) -> RunContext:
    return RunContext(ports=replace(Ports(), jobs=jobs))


def test_a_pending_job_runs_to_done_with_one_progress_event():
    jobs, p = FakeJobs(), payload("hello")
    result = graph.run(p, ctx(jobs))
    assert result == {"echo": "hello", "actor_user_id": str(p.actor_user_id)}
    assert jobs.status == "done" and jobs.fields["result"] == result
    assert [e["type"] for e in jobs.events] == ["status", "progress", "status"]
    assert jobs.events[1]["text"] == "Echoing 'hello'"


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_a_finished_job_redelivered_is_a_no_op(status: str):
    jobs = FakeJobs(status)
    assert graph.run(payload(), ctx(jobs)) == {"skipped": status} and jobs.events == []


def test_a_missing_job_is_skipped():
    jobs = FakeJobs()
    jobs.missing = True
    assert graph.run(payload(), ctx(jobs)) == {"skipped": "missing job"}
