"""Job bookkeeping over Supabase's REST API (service role).

Vendored per service on purpose (PLAN.md §4): a function imports only its own package and
`contracts`, so each one carries this small store rather than sharing the API's repositories.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

import httpx

from contracts.jobs import JobEventType, JobStatus


class JobStore:
    def __init__(self, url: str, service_role_key: str, client: httpx.Client | None = None) -> None:
        self._rest = f"{url.rstrip('/')}/rest/v1"
        self._client = client or httpx.Client(timeout=15.0)
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_env(cls) -> JobStore:
        return cls(os.environ["SUPABASE__URL"], os.environ["SUPABASE__SERVICE_ROLE_KEY"])

    def get(self, job_id: UUID) -> dict[str, Any] | None:
        r = self._client.get(f"{self._rest}/jobs", headers=self._headers,
                             params={"id": f"eq.{job_id}", "select": "id,status"})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else None

    def _patch(self, job_id: UUID, fields: dict[str, Any]) -> None:
        r = self._client.patch(f"{self._rest}/jobs", headers=self._headers,
                               params={"id": f"eq.{job_id}"}, json=fields)
        r.raise_for_status()

    def set_status(self, job_id: UUID, status: JobStatus) -> None:
        self._patch(job_id, {"status": status.value})
        self.event(job_id, JobEventType.STATUS, {"status": status.value})

    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any],
              agent: str | None = None) -> None:
        r = self._client.post(f"{self._rest}/job_events", headers=self._headers,
                              json={"job_id": str(job_id), "type": type_.value,
                                    "agent": agent, "payload": payload})
        r.raise_for_status()

    def finish(self, job_id: UUID, result: dict[str, Any]) -> None:
        self._patch(job_id, {"status": JobStatus.DONE.value, "result": result})
        self.event(job_id, JobEventType.STATUS, {"status": JobStatus.DONE.value})

    def fail(self, job_id: UUID, error: str) -> None:
        try:
            self._patch(job_id, {"status": JobStatus.FAILED.value, "error": error})
            self.event(job_id, JobEventType.STATUS, {"status": JobStatus.FAILED.value})
        except httpx.HTTPError:
            pass  # nothing more we can do; Cloud Logging has the original exception
