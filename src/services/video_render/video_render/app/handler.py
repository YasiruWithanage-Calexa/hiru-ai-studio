"""HTTP entry: payload → the renders of one press of Generate. The echo template's contract: 400 for a bad payload;
a crash marks the job failed and answers 200 (a re-delivery could pay for a second video); 500 only for a transient
network error before a render was submitted. A refusal or a failed render is a RESULT: recorded on its row, answered
200, never retried."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from pydantic import ValidationError

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from video_render.engine import render
from video_render.runtime.config import Config, get_config
from video_render.runtime.jobs import Jobs
from video_render.runtime.rest import Rest, Row
from video_render.runtime.store import Store

_logger = logging.getLogger(__name__)
AGENT = "video_render"
WORKERS = 4  # a job's renders run at once (a press makes contracts.video_gen.MAX_TAKES_PER_PRESS, now one)


def run(payload: DispatchPayload, store: Store, jobs: Jobs, cfg: Config) -> Row:
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    job_id, production_id = payload.job_id, payload.production_id
    assert production_id is not None
    jobs.set(job_id, JobStatus.RUNNING)
    rows = store.renders([str(r) for r in payload.state.get("render_ids") or []])
    counts = {"done": 0, "failed": 0, "refused": 0, "skipped": 0}

    def one(row: Row) -> tuple[Row, str]:
        try:
            return row, render.run_render(store, cfg, row, job_id=str(job_id), actor=str(payload.actor_user_id))
        except httpx.TransportError:
            raise
        except Exception:
            _logger.exception("render %s crashed", row.get("id"))
            store.finish_render(str(row["id"]), {"status": "failed", "error": render.FAILED})
            return row, "failed"

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for row, status in pool.map(one, rows):
            counts[status] += 1
            if status != "skipped":
                jobs.event(job_id, JobEventType.PROGRESS if status == "done" else JobEventType.WARNING,
                           {"text": "Take ready" if status == "done" else f"Take {status}",
                            "render_id": str(row["id"]), "shot_id": str(row["shot_id"]), "status": status},
                           agent=AGENT)
    if counts["done"]:
        store.audit({"production_id": str(production_id), "actor_user_id": str(payload.actor_user_id),
                     "actor_agent": AGENT, "action": "take.render", "entity": "job", "entity_id": str(job_id),
                     "diff": counts})
    jobs.finish(payload, counts)
    return dict(counts)


def handle(request: Any) -> tuple[dict[str, Any], int]:
    try:
        payload = DispatchPayload.model_validate(request.get_json(silent=True) or {})
        if payload.production_id is None:
            raise ValueError("production_id is required")
    except (ValidationError, ValueError):
        return {"error": "bad payload"}, 400

    cfg = get_config()
    rest = Rest(cfg.supabase_url, cfg.service_role_key)
    store = Store(rest)
    jobs = Jobs(rest, cfg.api_internal_url, cfg.internal_secret)
    try:
        return run(payload, store, jobs, cfg), 200
    except httpx.TransportError:
        _logger.warning("transient network error job=%s", payload.job_id, exc_info=True)
        return {"error": "retry"}, 500
    except Exception:
        _logger.exception("video_render failed job=%s", payload.job_id)
        jobs.fail(payload.job_id, "Making the video failed.")
        return {"error": "failed"}, 200
