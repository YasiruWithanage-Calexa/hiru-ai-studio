"""Long-running work: the job row, its events, and the payload a function receives.

Flow: API creates a `jobs` row → enqueues the function (Cloud Tasks with OIDC in production,
a local HTTP POST in development) → the function marks the job running, appends `job_events`
as it works, and finishes it. The browser follows progress through Supabase Realtime on
`job_events` (RLS-filtered), so there is no Redis and no polling loop in the API.

Cloud Tasks re-delivers on failure, so every function must be idempotent for a given
`job_id`: re-running a finished job is a no-op.
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


class DispatchPayload(BaseModel):
    """The body every function receives."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    kind: JobKind
    actor_user_id: UUID
    production_id: UUID | None = None
    # Multi-hop pipelines: which hop this is, and the state carried from the previous one.
    cursor: int = 0
    state: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    kind: JobKind
    status: JobStatus
    production_id: UUID | None
    requested_by: UUID | None
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
