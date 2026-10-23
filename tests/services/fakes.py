"""Fakes shared by the engine tests: job bookkeeping and a model that answers by schema name.

No test calls OpenAI or any network service (CLAUDE.md).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from contracts.jobs import DispatchPayload, JobEventType, JobStatus


class FakeJobs:
    def __init__(self, status: str = "pending", cursor: int = 0) -> None:
        self.status = status
        self.cursor = cursor
        self.fields: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self.advanced: list[dict[str, Any]] = []  # courier calls: {"cursor", "state"}
        self.missing = False

    def check(self, payload: DispatchPayload) -> str | None:
        if self.missing:
            return "missing job"
        if self.status in ("done", "failed", "cancelled"):
            return self.status
        if self.cursor != payload.cursor:
            return "stale hop"
        if self.status == "waiting_input" and not payload.resuming:
            return "waiting for answers"
        return None

    def set(self, job_id: UUID, status: JobStatus, **fields: Any) -> None:
        self.status = status.value
        self.fields.update(fields)

    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None:
        self.events.append({"type": type_.value, "agent": agent, **payload})

    def stage(self, job_id: UUID, stage: str, state: str, text: str = "") -> None:
        self.events.append({"type": "stage", "stage": stage, "state": state, "text": text})

    def finish(self, payload: DispatchPayload, result: dict[str, Any],
               next_state: dict[str, Any] | None = None, *, again: bool = False) -> None:
        if payload.is_last_hop and not again:
            self.set(payload.job_id, JobStatus.DONE, result=result)
        else:
            self.advanced.append({"cursor": payload.cursor, "again": again,
                                  "state": {**(next_state or {}), "previous": result}})

    def texts(self, type_: str | None = None) -> list[str]:
        return [str(e.get("text", "")) for e in self.events if type_ is None or e["type"] == type_]

    def stages(self) -> list[tuple[str, str]]:
        return [(e["stage"], e["state"]) for e in self.events if e["type"] == "stage"]


Responder = Callable[[str, str], dict[str, Any]]  # (system, user) → answer


class FakeLLM:
    """`responders` maps a schema name to a function of (system, user). Missing → raises."""

    def __init__(self, responders: dict[str, Responder] | None = None, *, enabled: bool = True) -> None:
        self.responders = responders or {}
        self._enabled = enabled
        self.calls: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def json(self, *, tier: str, phase: str, system: str, user: str, schema_name: str,
             schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"tier": tier, "phase": phase, "schema": schema_name, "system": system, "user": user})
        if schema_name not in self.responders:
            raise RuntimeError(f"model unavailable for {schema_name}")
        return self.responders[schema_name](system, user)
