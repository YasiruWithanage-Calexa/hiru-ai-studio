"""Dispatch long-running work to Cloud Run functions, one hop at a time.

Pattern from PromptMotion `api/workers/task_manager.py` (commit 1d748dc):

* `dispatch()` writes the `jobs` row FIRST, then enqueues, so a job the browser is told about
  always exists. If enqueueing fails, the row is marked failed rather than left pending forever.
* Production: Cloud Tasks with an OIDC token (functions are internal-only and require it).
  Development (`LOCAL_FUNCTIONS=true`): an HTTP POST to the local functions-framework port.
* Functions never enqueue each other. A multi-hop job (the structure build) keeps its hop list
  in `jobs.request.pipeline`; a function that finished a hop calls `/internal/pipeline/advance`
  (the courier), which moves `jobs.cursor` on with a compare-and-set and sends the next hop.
* A hop that stopped on questions is re-sent by `resume()` once they are all answered.
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
from api.repositories import Repos, Row
from contracts.jobs import DispatchPayload, JobKind, JobStatus

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FunctionSpec:
    name: str  # Cloud Run function name, also its deploy name
    local_port: int  # functions-framework port in development (see scripts/start-functions.ps1)
    deadline_s: int = 600  # must equal the function's --timeout


FUNCTIONS: dict[JobKind, FunctionSpec] = {
    JobKind.ECHO: FunctionSpec("hiru-echo", 8201, 60),
    JobKind.DOC_INGEST: FunctionSpec("hiru-doc-ingest", 8202, 540),
    JobKind.SCRIPT_SPLIT: FunctionSpec("hiru-script-split", 8203, 900),
    JobKind.STRUCTURE_BUILD: FunctionSpec("hiru-structure-build", 8204, 900),
    JobKind.CANON_EXTRACT: FunctionSpec("hiru-canon-extract", 8205, 600),
    # Added as each engine lands (PLAN.md §13).
}


def function_url(spec: FunctionSpec, settings: Settings) -> str:
    if settings.local_functions:
        return f"http://localhost:{spec.local_port}/"
    base = settings.gcp.functions_base_url
    if not base:
        raise RuntimeError("GCP__FUNCTIONS_BASE_URL is not set")
    if "{function_name}" in base:
        return base.format(function_name=spec.name)
    return f"{base.rstrip('/')}/{spec.name}"


async def dispatch(
    kind: JobKind,
    repos: Repos,
    *,
    actor_user_id: UUID,
    production_id: UUID | None = None,
    request: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    pipeline: list[JobKind] | None = None,
) -> UUID:
    """Create the job row and send its first hop. `kind` names the job; `pipeline` lists the
    functions it runs through (default: just `kind`). Returns the job id."""
    hops = pipeline or [kind]
    for hop in hops:
        if hop not in FUNCTIONS:
            raise ValueError(f"no function registered for job kind {hop}")
    job_id = uuid4()
    await repos.jobs.create({
        "id": str(job_id), "kind": kind.value, "status": JobStatus.PENDING.value,
        "production_id": str(production_id) if production_id else None,
        "requested_by": str(actor_user_id),
        "request": {**(request or {}), "pipeline": [h.value for h in hops]},
    })
    payload = DispatchPayload(job_id=job_id, kind=hops[0], actor_user_id=actor_user_id,
                              production_id=production_id, pipeline=hops, cursor=0, state=state or {})
    await _send_or_fail(payload, repos)
    return job_id


def _pipeline_of(job: Row) -> list[JobKind]:
    hops = (job.get("request") or {}).get("pipeline") or [job["kind"]]
    return [JobKind(h) for h in hops]


async def advance(repos: Repos, job: Row, from_cursor: int, state: dict[str, Any], *,
                  again: bool = False) -> bool:
    """The courier: hop `from_cursor` is finished; send the next. False when this hand-off was
    already made (a re-delivered callback) or the job is no longer running.

    `again`: the hop ran out of time with work left. The same function is inserted after it in
    the job's pipeline and sent, so every delivery still has its own cursor and the same
    compare-and-set keeps a duplicate callback from sending it twice."""
    hops = _pipeline_of(job)
    request = None
    if again:
        hops = [*hops[: from_cursor + 1], hops[from_cursor], *hops[from_cursor + 1:]]
        request = {**(job.get("request") or {}), "pipeline": [h.value for h in hops]}
    if from_cursor + 1 >= len(hops):
        return False
    if not await repos.jobs.advance(UUID(str(job["id"])), from_cursor, request):
        return False
    payload = DispatchPayload(job_id=job["id"], kind=hops[from_cursor + 1], actor_user_id=job["requested_by"],
                              production_id=job.get("production_id"), pipeline=hops, cursor=from_cursor + 1,
                              state=state)
    await _send_or_fail(payload, repos)
    return True


async def resume(repos: Repos, job: Row, state: dict[str, Any] | None = None) -> bool:
    """Re-send the hop that is waiting for answers. False when another request already did."""
    if not await repos.jobs.claim_resume(UUID(str(job["id"]))):
        return False
    hops = _pipeline_of(job)
    cursor = int(job.get("cursor") or 0)
    payload = DispatchPayload(job_id=job["id"], kind=hops[cursor], actor_user_id=job["requested_by"],
                              production_id=job.get("production_id"), pipeline=hops, cursor=cursor,
                              state={**(state or {}), "resume": True})
    await _send_or_fail(payload, repos)
    return True


async def _send_or_fail(payload: DispatchPayload, repos: Repos) -> None:
    settings = get_settings()
    spec = FUNCTIONS[payload.kind]
    try:
        if settings.local_functions:
            _fire_local(function_url(spec, settings), payload)
        else:
            await asyncio.to_thread(_enqueue_cloud_task, spec, payload, settings)
    except Exception as exc:
        _logger.exception("dispatch failed kind=%s job=%s", payload.kind, payload.job_id)
        await repos.jobs.mark_failed(payload.job_id, "The job could not be started.")
        raise RuntimeError("dispatch failed") from exc


_background: set[asyncio.Task[None]] = set()


def _fire_local(url: str, payload: DispatchPayload) -> None:
    """Fire-and-forget POST to a local function (development only)."""

    async def call() -> None:
        try:
            async with httpx.AsyncClient(timeout=900.0) as client:
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
    client.create_task(request={"parent": parent, "task": task})
