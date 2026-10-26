"""HTTP entry: payload → pipeline. The echo template's contract: 400 for a malformed payload;
a crash marks the job failed and answers 200 (a retry will not fix it); 500 only for a
transient network error, which a Cloud Tasks retry can fix."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.jobs import DispatchPayload
from shot_producer.engine import pipeline
from shot_producer.runtime.config import get_config
from shot_producer.runtime.jobs import Jobs
from shot_producer.runtime.llm import LLM
from shot_producer.runtime.rest import Rest
from shot_producer.runtime.store import Store

_logger = logging.getLogger(__name__)


def build(payload: DispatchPayload) -> tuple[Store, Jobs, LLM]:
    config = get_config()
    rest = Rest(config.supabase_url, config.service_role_key)
    store = Store(rest)

    def on_usage(row: dict[str, Any]) -> None:
        store.record_usage({**row, "job_id": str(payload.job_id),
                            "production_id": str(payload.production_id) if payload.production_id else None,
                            "actor_user_id": str(payload.actor_user_id)})

    return store, Jobs(rest, config.api_internal_url, config.internal_secret), LLM(config, on_usage)


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        if payload.production_id is None:
            raise ValueError("production_id is required")
    except (ValidationError, ValueError):
        return {"error": "bad payload"}, 400

    store, jobs, llm = build(payload)
    try:
        return pipeline.run(payload, store, jobs, llm), 200
    except httpx.TransportError:
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("shot_producer failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Designing the shots failed.")
        return {"error": "failed"}, 200
