"""Long-running work: the job row, its events, and the payload a function receives.

Flow: API creates a `jobs` row → enqueues the function (Cloud Tasks with OIDC in production,
a local HTTP POST in development) → the function marks the job running, appends `job_events`
as it works, and finishes it. The browser follows progress through Supabase Realtime on
`job_events` (RLS-filtered), so there is no Redis and no polling loop in the API.

Cloud Tasks re-delivers on failure, so every function must be idempotent for a given
`job_id`: re-running a finished job is a no-op.

Multi-hop jobs (PLAN.md §3, the "courier"): one job can run through several functions in turn,
e.g. the structure build is canon_extract → structure_build → script_split under ONE job id, so
the live-build screen follows a single job. The API fixes the hop list (`pipeline`) when it
creates the job; a function that finishes a hop that is not the last asks the API to send the
next one (`POST /internal/pipeline/advance`). Functions never enqueue each other. `jobs.cursor`
is the hop in flight; a delivery whose `cursor` is behind it is a stale re-delivery and is
skipped.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobKind(StrEnum):
    """Each kind maps to exactly one function (`api/workers/task_manager.FUNCTIONS`)."""

    ECHO = "echo"  # Phase 0 smoke test of the dispatch path
    DOC_INGEST = "doc_ingest"
    STRUCTURE_BUILD = "structure_build"
    CANON_EXTRACT = "canon_extract"
    SCRIPT_SPLIT = "script_split"
    SHOT_PRODUCE = "shot_produce"
    FRAME_RENDER = "frame_render"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"  # paused on a question to a person
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED})


class JobEventType(StrEnum):
    STATUS = "status"
    PROGRESS = "progress"  # "Scene writer: Episode 2, scene 4 of 9"
    AGENT_STEP = "agent_step"  # one agent's visible contribution
    QUESTION = "question"  # the graph is waiting for an answer
    WARNING = "warning"
    STAGE = "stage"  # a build stage changed state: {"stage": ..., "state": "active" | "done"}


class DispatchPayload(BaseModel):
    """The body every function receives."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    kind: JobKind
    actor_user_id: UUID
    production_id: UUID | None = None
    # Multi-hop pipelines: every hop in order, which one this is, and the state carried from
    # the previous hop. A single-function job has a pipeline of one (or none, for old payloads).
    pipeline: list[JobKind] = Field(default_factory=list)
    cursor: int = Field(default=0, ge=0)
    state: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_last_hop(self) -> bool:
        return self.cursor + 1 >= len(self.pipeline)

    @property
    def resuming(self) -> bool:
        """True when the API re-sent this hop because the questions it asked were answered."""
        return bool(self.state.get("resume"))


class AdvanceRequest(BaseModel):
    """A function → API: hop `cursor` of `job_id` is finished; send the next one with `state`."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    cursor: int = Field(ge=0)
    state: dict[str, Any] = Field(default_factory=dict)
    # True: the hop ran out of time with work left; send the SAME function again with `state`
    # (inserted into the pipeline after this hop) instead of the next one.
    again: bool = False


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    kind: JobKind
    status: JobStatus
    production_id: UUID | None
    requested_by: UUID | None
    cursor: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: UUID
    seq: int
    type: JobEventType
    agent: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
