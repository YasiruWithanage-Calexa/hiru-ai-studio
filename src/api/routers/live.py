"""The status read the interface polls while work runs (plan/2026-11-08c phase 3).

It answers one small question for one production: what is still queued or running, and what changed since the
caller last asked. It reads named columns of four tables, mints no ticket, and loads no canon, looks or prompts, so a
poll every three seconds costs almost nothing. (`/activity` is the audit log; this is `/live`.)
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.cache import job_ended
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["live"])

ACTIVE = frozenset({"pending", "queued", "running", "processing"})


class LiveItem(BaseModel):
    kind: Literal["frame", "render", "document", "job"]
    id: str
    shot_id: str | None = None
    status: str
    job_kind: str | None = None  # for kind "job": which job
    updated_at: datetime


class Live(BaseModel):
    busy: bool  # any item still active: the caller polls only while this is true
    version: datetime | None  # newest `updated_at` seen; pass it back as `since`
    items: list[LiveItem]


def _items(kind: Literal["frame", "render", "document", "job"], rows: list[Row]) -> list[LiveItem]:
    return [LiveItem(kind=kind, id=str(r["id"]), shot_id=str(r["shot_id"]) if r.get("shot_id") else None,
                     status=str(r["status"]), job_kind=str(r["kind"]) if kind == "job" else None,
                     updated_at=r["updated_at"]) for r in rows]


@router.get("/live", response_model=Live)
async def get_live(production_id: UUID,
                   _: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                   repos: Annotated[Repos, Depends(get_repos)],
                   since: Annotated[datetime | None, Query(description="items that changed after this too")] = None,
                   ) -> Live:
    frames, renders, documents, jobs = await asyncio.gather(
        repos.frames.live(production_id, since), repos.renders.live(production_id, since),
        repos.documents.live(production_id, since), repos.jobs.live(production_id, since))
    items = [*_items("frame", frames), *_items("render", renders), *_items("document", documents),
             *_items("job", jobs)]
    items.sort(key=lambda i: i.updated_at)
    if any(i.status not in ACTIVE for i in items):
        job_ended()  # something finished: workers wrote rows this process may still hold a copy of
    return Live(busy=any(i.status in ACTIVE for i in items),
                version=max((i.updated_at for i in items), default=since), items=items)
