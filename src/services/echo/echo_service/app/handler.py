"""The echo job: the smallest function that exercises the whole job lifecycle.

    pending → running → (event) → done, with the result written once.

It is the template every engine function follows: parse the payload into the contract, skip a
job that is already finished (Cloud Tasks re-delivers), do the work, append events, finish. An
exception marks the job failed and still answers 200, because a non-2xx answer makes Cloud Tasks
retry a job that failed for a reason a retry will not fix. Errors worth retrying should raise
`Retryable` instead (none here).
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from echo_service.runtime.jobs import JobStore

_logger = logging.getLogger(__name__)


class Retryable(Exception):
    """Raise to answer 500 so Cloud Tasks retries the invocation."""


def run(payload: DispatchPayload, store: JobStore) -> dict[str, Any]:
    job = store.get(payload.job_id)
    if job is None:
        _logger.warning("echo: job %s does not exist", payload.job_id)
        return {"skipped": "missing"}
    if job["status"] in ("done", "failed", "cancelled"):
        return {"skipped": job["status"]}

    store.set_status(payload.job_id, JobStatus.RUNNING)
    message = str(payload.state.get("message", ""))
    store.event(payload.job_id, JobEventType.PROGRESS, {"text": f"Echoing {message!r}"}, agent="echo")
    result = {"echo": message, "actor_user_id": str(payload.actor_user_id)}
    store.finish(payload.job_id, result)
    return result


def handle(request: Any) -> tuple[dict[str, Any], int]:
    """functions-framework HTTP entry point (a Flask request)."""
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return {"error": "bad payload", "detail": exc.errors(include_url=False)}, 400

    store = JobStore.from_env()
    try:
        return run(payload, store), 200
    except Retryable:
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("echo failed job=%s", payload.job_id)
        store.fail(payload.job_id, "The echo job failed.")
        return {"error": "failed"}, 200
