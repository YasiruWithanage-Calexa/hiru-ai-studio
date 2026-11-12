"""HTTP entry: payload → graph. The echo template's contract: 400 for a malformed payload;
a crash marks the job failed and answers 200; 500 only for a transient network or database
error, which a Cloud Tasks retry can fix (and, with durable checkpoints, resumes)."""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import psycopg
from pydantic import ValidationError

from canon_extract.engine import pipeline
from canon_extract.runtime.checkpoint import saver
from canon_extract.runtime.config import get_config
from canon_extract.runtime.jobs import Jobs
from canon_extract.runtime.llm import LLM
from canon_extract.runtime.rest import Rest
from canon_extract.runtime.store import Store
from contracts.jobs import DispatchPayload, JobKind

_logger = logging.getLogger(__name__)


def run_graph(payload: DispatchPayload, jobs: Jobs, checkpointer: Any) -> dict[str, Any]:
    """The same job through the `hiru_ai` canon_extract system (AI_ENGINE=graph)."""
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.canon_extract import graph

    return graph.run(payload, supabase_rest.build_context(payload, jobs=jobs), checkpointer)


def run_refine(payload: DispatchPayload, jobs: Jobs) -> dict[str, Any]:
    """plan/2026-11-12c: the canon refine (`JobKind.CANON_REFINE`), served by this function beside canon_extract."""
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.breakdown.breakdown_canon_refine import graph

    return graph.run(payload, supabase_rest.build_context(payload, jobs=jobs))


def _breakdown_on() -> bool:
    """plan/2026-11-11 §6: with BREAKDOWN__ENABLED the graph runs, where the steps the breakdown absorbs are retired."""
    from hiru_ai.core.settings import get_settings

    return get_settings().breakdown.enabled


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
        if payload.kind is JobKind.CANON_REFINE:
            return run_refine(payload, jobs), 200
        with saver(config.db_url) as (checkpointer, _durable):
            if os.environ.get("AI_ENGINE", "legacy") == "graph" or _breakdown_on():
                return run_graph(payload, jobs, checkpointer), 200
            return pipeline.run(payload, store, jobs, LLM(config, on_usage), checkpointer), 200
    except (httpx.TransportError, psycopg.OperationalError):
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("canon_extract failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Refining the canon failed. The canon is as it was."
                  if payload.kind is JobKind.CANON_REFINE else "Extracting the canon failed.")
        return {"error": "failed"}, 200
