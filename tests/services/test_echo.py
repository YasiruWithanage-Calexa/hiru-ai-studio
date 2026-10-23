"""The echo function's lifecycle: the template every engine function follows."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "services" / "echo"))

from echo_service.app import handler

from contracts.jobs import DispatchPayload, JobEventType, JobKind, JobStatus


class FakeStore:
    def __init__(self, status: str | None = "pending") -> None:
        self.status = status
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.result: dict[str, Any] | None = None
        self.error: str | None = None

    def get(self, job_id: UUID) -> dict[str, Any] | None:
        return None if self.status is None else {"id": str(job_id), "status": self.status}

    def set_status(self, job_id: UUID, status: JobStatus) -> None:
        self.status = status.value
        self.events.append(("status", {"status": status.value}))

    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any],
              agent: str | None = None) -> None:
        self.events.append((type_.value, payload))

    def finish(self, job_id: UUID, result: dict[str, Any]) -> None:
        self.status, self.result = "done", result
        self.events.append(("status", {"status": "done"}))

    def fail(self, job_id: UUID, error: str) -> None:
        self.status, self.error = "failed", error


def _payload(message: str = "hi") -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.ECHO, actor_user_id=uuid4(),
                           state={"message": message})


def test_runs_pending_job_to_done():
    store = FakeStore()
    result = handler.run(_payload("hello"), store)  # type: ignore[arg-type]
    assert result["echo"] == "hello" and store.status == "done"
    assert [e[0] for e in store.events] == ["status", "progress", "status"]


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_redelivered_finished_job_is_a_no_op(status: str):
    store = FakeStore(status)
    assert handler.run(_payload(), store) == {"skipped": status}  # type: ignore[arg-type]
    assert store.events == []


def test_missing_job_is_skipped():
    assert handler.run(_payload(), FakeStore(None)) == {"skipped": "missing"}  # type: ignore[arg-type]


class _Req:
    def __init__(self, body: Any) -> None:
        self.body = body

    def get_json(self, silent: bool = False) -> Any:
        return self.body


def test_bad_payload_is_400_and_never_touches_the_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handler.JobStore, "from_env", classmethod(lambda cls: pytest.fail("store used")))
    body, code = handler.handle(_Req({"job_id": "nope"}))
    assert code == 400 and body["error"] == "bad payload"


def test_crash_marks_failed_and_answers_200_so_tasks_does_not_retry(monkeypatch: pytest.MonkeyPatch):
    store = FakeStore()
    monkeypatch.setattr(handler.JobStore, "from_env", classmethod(lambda cls: store))
    monkeypatch.setattr(handler, "run", lambda p, s: (_ for _ in ()).throw(RuntimeError("boom")))
    _, code = handler.handle(_Req(_payload().model_dump(mode="json")))
    assert code == 200 and store.status == "failed"
