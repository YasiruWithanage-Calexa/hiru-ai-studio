"""Dispatch long-running work to a Cloud Run function.

Pattern from PromptMotion `api/workers/task_manager.py` (commit 1d748dc):

* `dispatch()` writes the `jobs` row FIRST, then enqueues, so a job the browser is told about
  always exists. If enqueueing fails, the row is marked failed rather than left pending forever.
* Production: Cloud Tasks with an OIDC token (functions are internal-only and require it).
  Development (`LOCAL_FUNCTIONS=true`): an HTTP POST to the local functions-framework port.
* Functions never enqueue each other. Multi-hop pipelines will advance through the API
  (the "courier"), added when the first one exists (Phase 2).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx

from api.config import Settings, get_settings
from api.repositories import Repos
from contracts.jobs import DispatchPayload, JobKind, JobStatus

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunctionSpec:
    name: str  # Cloud Run function name, also its deploy name
    local_port: int  # functions-framework port in development (see scripts/start-functions.ps1)
    deadline_s: int = 600  # must equal the function's --timeout


FUNCTIONS: dict[JobKind, FunctionSpec] = {
    JobKind.ECHO: FunctionSpec("hiru-echo", 8201, 60),
    # Added as each engine lands (PLAN.md §13):
    # JobKind.DOC_INGEST: FunctionSpec("hiru-doc-ingest", 8202),
}


def function_url(spec: FunctionSpec, settings: Settings) -> str:
    if settings.local_functions:
        return f"http://localhost:{spec.local_port}/"
    base = settings.gcp.functions_base_url
    if not base:
        raise RuntimeError("GCP__FUNCTIONS_BASE_URL is not set")
    return base.format(function_name=spec.name) if "{function_name}" in base else f"{base.rstrip('/')}/{spec.name}"


async def dispatch(
    kind: JobKind,
    repos: Repos,
    *,
    actor_user_id: UUID,
    production_id: UUID | None = None,
    request: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> UUID:
    """Create the job row and hand the job to its function. Returns the job id."""
    spec = FUNCTIONS.get(kind)
    if spec is None:
        raise ValueError(f"no function registered for job kind {kind}")
    settings = get_settings()
    job_id = uuid4()
    await repos.jobs.create({
        "id": str(job_id), "kind": kind.value, "status": JobStatus.PENDING.value,
        "production_id": str(production_id) if production_id else None,
        "requested_by": str(actor_user_id), "request": request or {},
    })
    payload = DispatchPayload(job_id=job_id, kind=kind, actor_user_id=actor_user_id,
                              production_id=production_id, state=state or {})
    try:
        if settings.local_functions:
            _fire_local(function_url(spec, settings), payload)
        else:
            await asyncio.to_thread(_enqueue_cloud_task, spec, payload, settings)
    except Exception as exc:
        _logger.exception("dispatch failed kind=%s job=%s", kind, job_id)
        await repos.jobs.mark_failed(job_id, "The job could not be started.")
        raise RuntimeError("dispatch failed") from exc
    return job_id


_background: set[asyncio.Task[None]] = set()


def _fire_local(url: str, payload: DispatchPayload) -> None:
    """Fire-and-forget POST to a local function (development only)."""

    async def call() -> None:
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                await client.post(url, json=payload.model_dump(mode="json"))
        except httpx.HTTPError:
            _logger.exception("local function call failed url=%s", url)

    task = asyncio.create_task(call())
    _background.add(task)  # keep a reference so the task is not garbage-collected mid-flight
    task.add_done_callback(_background.discard)


def _enqueue_cloud_task(spec: FunctionSpec, payload: DispatchPayload, settings: Settings) -> None:
    from google.cloud import tasks_v2  # imported lazily: not needed in local development

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(settings.gcp.project_id, settings.gcp.region, settings.gcp.tasks_queue)
    url = function_url(spec, settings)
    task: dict[str, Any] = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload.model_dump(mode="json")).encode(),
            "oidc_token": {"service_account_email": settings.gcp.tasks_invoker_sa, "audience": url},
        },
        "dispatch_deadline": {"seconds": spec.deadline_s},
    }
    client.create_task(parent=parent, task=task)
