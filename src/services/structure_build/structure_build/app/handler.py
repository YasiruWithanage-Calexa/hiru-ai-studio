"""HTTP entry: payload → graph. The echo template's contract: 400 for a malformed payload;
a crash marks the job failed and answers 200; 500 only for a transient network or database
error, which a Cloud Tasks retry can fix (and, with durable checkpoints, resumes)."""
from __future__ import annotations

import logging
from typing import Any

import httpx
import psycopg
from pydantic import ValidationError

from contracts.jobs import DispatchPayload
from structure_build.engine import pipeline
from structure_build.runtime.checkpoint import saver
from structure_build.runtime.config import get_config
from structure_build.runtime.jobs import Jobs
from structure_build.runtime.llm import LLM
from structure_build.runtime.rest import Rest
from structure_build.runtime.store import Store

_logger = logging.getLogger(__name__)


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        if payload.production_id is None:
            raise ValueError("production_id is required")
    except (ValidationError, ValueError):
        return {"error": "bad payload"}, 400

    config = get_config()
    rest = Rest(config.supabase_url, config.service_role_key)
    store = Store(rest)
    jobs = Jobs(rest, config.api_internal_url, config.internal_secret)

    def on_usage(row: dict[str, Any]) -> None:
        store.record_usage({**row, "job_id": str(payload.job_id), "production_id": str(payload.production_id),
                            "actor_user_id": str(payload.actor_user_id)})

    try:
        with saver(config.db_url) as (checkpointer, durable):
            return pipeline.run(payload, store, jobs, LLM(config, on_usage), checkpointer, durable=durable), 200
    except (httpx.TransportError, psycopg.OperationalError):
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("structure_build failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Building the structure failed.")
        return {"error": "failed"}, 200
