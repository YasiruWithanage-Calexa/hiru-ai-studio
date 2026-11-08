"""HTTP entry: payload → the `raphael_shot_planner` system (plan/2026-11-08e). The echo template's contract: 400
for a
malformed payload; a crash marks the job failed and answers 200 (a retry will not fix it); 500 only for a transient
network error, which a Cloud Tasks retry can fix.

Shot Planner Raphael has no legacy engine to switch back to: the function is a thin handler that builds the run's
context
with the real adapters and hands over. With no model key the system fails the job and names the classic planner."""
from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.jobs import DispatchPayload
from shot_planner_raphael.runtime.config import get_config
from shot_planner_raphael.runtime.jobs import Jobs
from shot_planner_raphael.runtime.rest import Rest

_logger = logging.getLogger(__name__)


def build_jobs() -> Jobs:
    config = get_config()
    return Jobs(Rest(config.supabase_url, config.service_role_key), config.api_internal_url, config.internal_secret)


def run_graph(payload: DispatchPayload, jobs: Jobs) -> dict[str, Any]:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.systems.raphael.raphael_shot_planner import graph

    return graph.run(payload, supabase_rest.build_context(payload, jobs=jobs))


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        if payload.production_id is None:
            raise ValueError("production_id is required")
    except (ValidationError, ValueError):
        return {"error": "bad payload"}, 400

    jobs = build_jobs()
    try:
        return run_graph(payload, jobs), 200
    except httpx.TransportError:
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("shot_planner_raphael failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Planning shots with Raphael failed. Use the classic planner for this scene.")
        return {"error": "failed"}, 200
