"""The status read the interface polls while work runs (plan/2026-11-08c phase 3).

It answers one small question for one production: what is still queued or running, and what changed since the
caller last asked. It reads named columns of four tables (one query with schema v25's `live_items()`, plan/2026-11-13d
phase 3), mints no ticket, and loads no canon, looks or prompts, so a poll every three seconds costs almost nothing. The
structure build's item carries its newest event number (`seq`), so the build page reads only what is new.
(`/activity` is the audit log; this is `/live`.)
"""
from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from api.cache import job_ended
from api.config import LiveSettings, get_settings
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.live.hub import CLOSE, LiveHub, Subscriber
from api.repositories import Repos, Row
from contracts.live import ACTIVE, BUILD, Live, LiveItem, LiveNotice
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["live"])

def _items(kind: Literal["frame", "render", "document", "job"], rows: list[Row]) -> list[LiveItem]:
    return [LiveItem(kind=kind, id=str(r["id"]), shot_id=str(r["shot_id"]) if r.get("shot_id") else None,
                     status=str(r["status"]), job_kind=str(r["kind"]) if kind == "job" else None,
                     updated_at=r["updated_at"]) for r in rows]


async def _read_tables(repos: Repos, production_id: UUID, since: datetime | None) -> list[LiveItem]:
    """Before schema v25: the four tables, then the build's newest event number."""
    frames, renders, documents, jobs = await asyncio.gather(
        repos.frames.live(production_id, since), repos.renders.live(production_id, since),
        repos.documents.live(production_id, since), repos.jobs.live(production_id, since))
    items = [*_items("frame", frames), *_items("render", renders), *_items("document", documents),
             *_items("job", jobs)]
    builds = [i for i in items if i.kind == "job" and i.job_kind == BUILD]
    for item, seq in zip(builds, await asyncio.gather(*(repos.jobs.last_seq(UUID(i.id)) for i in builds)), strict=True):
        item.seq = seq
    return items


async def read_live(repos: Repos, production_id: UUID, since: datetime | None) -> Live:
    """What `/live` answers; also the stream's catch-up (plan/2026-11-13d phase 5)."""
    rows = await repos.jobs.live_items(production_id, since)  # schema v25: one query (plan/2026-11-13d phase 3)
    if rows is not None:
        items = [LiveItem(kind=r["kind"], id=str(r["id"]), shot_id=str(r["shot_id"]) if r.get("shot_id") else None,
                          status=str(r["status"]), job_kind=r.get("job_kind"), updated_at=r["updated_at"],
                          seq=r.get("seq")) for r in rows]
    else:
        items = await _read_tables(repos, production_id, since)
    items.sort(key=lambda i: i.updated_at)
    if any(i.status not in ACTIVE for i in items):
        job_ended()  # something finished: workers wrote rows this process may still hold a copy of
    return Live(busy=any(i.status in ACTIVE for i in items),
                version=max((i.updated_at for i in items), default=since), items=items)


@router.get("/live", response_model=Live)
async def get_live(production_id: UUID,
                   _: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                   repos: Annotated[Repos, Depends(get_repos)],
                   since: Annotated[datetime | None, Query(description="items that changed after this too")] = None,
                   ) -> Live:
    return await read_live(repos, production_id, since)


def _frame(event: str, data: dict[str, object], version: datetime) -> bytes:
    return f"event: {event}\nid: {version.isoformat()}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def _frames(hub: LiveHub, sub: Subscriber, catch: Live, cfg: LiveSettings) -> AsyncIterator[bytes]:
    """The catch-up, then each change once, a comment line while quiet; ends after `max_s`, after `idle_s` with nothing
    of the production active, when a newer tab of the same person takes its place, or when the client falls behind."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    sent: dict[str, tuple[str, int | None]] = {}
    active: set[str] = set()
    idle_from: float | None = None

    def frame(message: object) -> bytes | None:
        if isinstance(message, LiveItem):
            key = f"{message.kind}:{message.id}"
            if sent.get(key) == (message.status, message.seq):
                return None  # the catch-up and the live change of one moment are sent once
            sent[key] = (message.status, message.seq)
            if message.status in ACTIVE:
                active.add(key)
            else:
                active.discard(key)
                job_ended()  # as `/live` does: workers wrote rows this process may hold a copy of
            return _frame("item", message.model_dump(mode="json"), message.updated_at)
        if isinstance(message, LiveNotice):
            return _frame("notice", message.model_dump(mode="json"), message.at)
        return None

    try:
        yield b": open\n\n"
        for item in catch.items:
            if (out := frame(item)) is not None:
                yield out
        while True:
            now = loop.time()
            idle_from = (idle_from or now) if not active else None
            idle_left = cfg.idle_s - (now - idle_from) if idle_from is not None else math.inf
            left = min(cfg.max_s - (now - start), idle_left)
            if left <= 0:
                break
            try:
                message = await asyncio.wait_for(sub.queue.get(), timeout=min(cfg.keepalive_s, left))
            except TimeoutError:
                yield b": keep-alive\n\n"
                continue
            if message is CLOSE:
                break
            if (out := frame(message)) is not None:
                yield out
    finally:
        await hub.close(sub)


@router.get("/stream")
async def stream(production_id: UUID, request: Request,
                 access: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                 repos: Annotated[Repos, Depends(get_repos)],
                 since: Annotated[datetime | None, Query(description="the last version this page has")] = None,
                 ) -> StreamingResponse:
    """Work in progress, pushed (plan/2026-11-13d phase 5): the `/live` shapes as server-sent events, each with the
    version to reconnect from. 404 while `LIVE__TRANSPORT=poll`, which tells the browser to poll `/live`. Access is
    checked when it opens; it ends by itself within `LIVE__MAX_S`, so every reconnect checks it again."""
    cfg = get_settings().live
    if cfg.transport != "stream":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The status stream is off: poll /live.")
    hub: LiveHub = request.app.state.live_hub
    sub = await hub.open(production_id, access.user.id)  # before the catch-up, so nothing falls between them
    try:
        catch = await read_live(repos, production_id, since)
    except BaseException:
        await hub.close(sub)
        raise
    return StreamingResponse(_frames(hub, sub, catch, cfg), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
