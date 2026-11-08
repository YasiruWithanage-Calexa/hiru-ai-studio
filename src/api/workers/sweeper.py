"""Ends work that nobody is doing any more (plan/2026-11-08c phase 5, D6).

A frame, render, document or job can be left `queued` / `running` when its worker dies. The interface polls
while anything is busy, so one such row meant a poller that never stopped. Once a minute this marks every row
that has made no progress for its limit as `failed`, with a plain reason. "Progress" for a job is its row
changing or a `job_events` row; for a frame, render or document it is the row changing (the workers touch it
through `updated_at`). A job waiting on a person's answer (`waiting_input`) is never swept.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from api.repositories import Repos, Row
from contracts.jobs import JobKind

_logger = logging.getLogger(__name__)

SWEEP_EVERY_S = 60.0

# D6: frame 10 min, take 30 (Veo is slow), document 20, any other job 15.
FRAME_LIMIT = timedelta(minutes=10)
RENDER_LIMIT = timedelta(minutes=30)
DOCUMENT_LIMIT = timedelta(minutes=20)
JOB_LIMIT = timedelta(minutes=15)
JOB_LIMITS: dict[str, timedelta] = {
    JobKind.FRAME_RENDER.value: FRAME_LIMIT,
    JobKind.VIDEO_RENDER.value: RENDER_LIMIT,
    JobKind.DOC_INGEST.value: DOCUMENT_LIMIT,
}


def reason(limit: timedelta) -> str:
    return f"Stopped: no progress for {int(limit.total_seconds() // 60)} minutes."


def _when(value: object) -> datetime:
    when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


async def sweep(repos: Repos, now: datetime | None = None) -> int:
    """One pass. Returns how many rows were ended."""
    now = now or datetime.now(UTC)
    ended = 0

    # Jobs. The cheap read uses the shortest limit; each candidate then gets its own limit and its events checked.
    jobs: list[Row] = await repos.jobs.active_before(now - min(JOB_LIMITS.values()))
    failed_jobs: dict[str, timedelta] = {}
    for job in jobs:
        limit = JOB_LIMITS.get(str(job["kind"]), JOB_LIMIT)
        last = _when(job["updated_at"])
        event = await repos.jobs.last_event_at(job["id"])
        if event is not None:
            last = max(last, _when(event))
        if now - last < limit:
            continue
        await repos.jobs.mark_failed(job["id"], reason(limit))
        failed_jobs[str(job["id"])] = limit
        ended += 1

    # Frames and renders: those of a job just failed, and any other that has gone quiet for its own limit.
    frames = await repos.frames.active_before(now)  # the busy set is small; each row is judged below
    stuck = [str(f["id"]) for f in frames
             if str(f.get("job_id")) in failed_jobs or now - _when(f["updated_at"]) >= FRAME_LIMIT]
    if stuck:
        await repos.frames.update_many(stuck, {"status": "failed", "error": reason(FRAME_LIMIT)})
        ended += len(stuck)
    renders = await repos.renders.active_before(now)
    stuck_renders = [str(r["id"]) for r in renders
                     if str(r.get("job_id")) in failed_jobs or now - _when(r["updated_at"]) >= RENDER_LIMIT]
    if stuck_renders:
        await repos.renders.update_many(stuck_renders, {"status": "failed", "error": reason(RENDER_LIMIT)})
        ended += len(stuck_renders)

    for doc in await repos.documents.processing_before(now - DOCUMENT_LIMIT):
        await repos.documents.update(doc["id"], {"status": "failed", "error": reason(DOCUMENT_LIMIT)})
        ended += 1

    if ended:
        _logger.warning("sweeper ended %d stuck rows", ended)
    return ended


async def run_forever(repos: Repos, every_s: float = SWEEP_EVERY_S) -> None:
    while True:
        await asyncio.sleep(every_s)
        with contextlib.suppress(Exception):  # a database blip must not stop the loop
            await sweep(repos)
