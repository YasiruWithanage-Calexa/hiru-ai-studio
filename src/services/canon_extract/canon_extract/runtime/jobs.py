"""Job bookkeeping and the courier hand-off. Vendored per service (PLAN.md §4).

    check(payload)   → skip reason, or None to run (finished job, or a stale re-delivery of a
                       hop the job has already moved past)
    finish(...)      → the last hop marks the job done; any other hop asks the API to send the
                       next one (`POST /internal/pipeline/advance`). Functions never enqueue
                       each other.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from canon_extract.runtime.rest import Rest, Row
from contracts.jobs import AdvanceRequest, DispatchPayload, JobEventType, JobStatus

TERMINAL = ("done", "failed", "cancelled")


class Jobs:
    def __init__(self, rest: Rest, api_internal_url: str, internal_secret: str) -> None:
        self.rest = rest
        self.api = api_internal_url.rstrip("/")
        self.secret = internal_secret

    def get(self, job_id: UUID) -> Row | None:
        return self.rest.first("jobs", {"id": f"eq.{job_id}", "select": "id,status,cursor"})

    def check(self, payload: DispatchPayload) -> str | None:
        job = self.get(payload.job_id)
        if job is None:
            return "missing job"
        if job["status"] in TERMINAL:
            return str(job["status"])
        if int(job.get("cursor") or 0) != payload.cursor:
            return "stale hop"
        if job["status"] == JobStatus.WAITING_INPUT and not payload.resuming:
            return "waiting for answers"
        return None

    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None:
        self.rest.patch("jobs", {"id": f"eq.{job_id}"}, {"status": status.value, **fields})
        self.event(job_id, JobEventType.STATUS, {"status": status.value})

    def event(self, job_id: UUID, type_: JobEventType, payload: Row, agent: str | None = None) -> None:
        self.rest.insert("job_events", [{"job_id": str(job_id), "type": type_.value,
                                         "agent": agent, "payload": payload}])

    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None:
        self.event(job_id, JobEventType.STAGE, {"stage": stage, "state": state, "text": text})

    def finish(self, payload: DispatchPayload, result: Row, next_state: Row | None = None,
               *, again: bool = False) -> None:
        """`again`: work is left; the same function runs once more with `next_state`."""
        if payload.is_last_hop and not again:
            self.set(payload.job_id, JobStatus.DONE, result=result)
            return
        body = AdvanceRequest(job_id=payload.job_id, cursor=payload.cursor, again=again,
                              state={**(next_state or {}), "previous": result})
        r = httpx.post(f"{self.api}/internal/pipeline/advance", json=body.model_dump(mode="json"),
                       headers={"X-Internal-Secret": self.secret}, timeout=30.0)
        r.raise_for_status()

    def fail(self, job_id: UUID, error: str) -> None:
        try:
            self.set(job_id, JobStatus.FAILED, error=error)
        except httpx.HTTPError:
            pass  # nothing more to do; Cloud Logging has the original exception
