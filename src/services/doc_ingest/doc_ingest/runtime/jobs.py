"""The job contract `hiru_ai` systems use (`hiru_ai.core.ports.Jobs`), over this function's own store.

doc_ingest is a single-hop job: it has no cursor and no courier, so `finish` marks the job done with its result.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from contracts.jobs import JobEventType, JobStatus
from doc_ingest.runtime.store import Store

TERMINAL = ("done", "failed", "cancelled")


class JobsPort:
    def __init__(self, store: Store) -> None:
        self.store = store

    def check(self, payload: Any) -> str | None:
        job = self.store.get_job(payload.job_id)
        if job is None:
            return "missing job"
        return str(job["status"]) if job["status"] in TERMINAL else None

    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None:
        self.store.set_job(job_id, status, **fields)

    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None:
        self.store.event(job_id, type_, payload, agent)

    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None:
        self.store.event(job_id, JobEventType.STAGE, {"stage": stage, "state": state, "text": text})

    def finish(self, payload: Any, result: dict[str, Any], next_state: dict[str, Any] | None = None, *,
               again: bool = False) -> None:
        self.store.set_job(payload.job_id, JobStatus.DONE, result=result)
