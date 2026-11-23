"""Settings → Usage (plan/2026-11-23): what the studio spent in a month, in USD, admin only.

    GET /v1/admin/usage?month=2026-11      the month's total and each production, in three buckets

Every `*_micros` is a FINAL price (provider cost + the studio's margin). There is deliberately no field for a provider
cost, a margin, a rate or a token count: the margins are secret (`src/api/margins.yaml`), and a breakdown that could
reveal them must not reach the network tab. A member who is not an admin gets 403.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from api.deps.authz import Admin
from api.deps.db import get_repos
from api.repositories import Repos
from api.services import usage_totals as svc
from contracts import usage_totals as ut
from contracts.cost_parts import PurposeTotals
from contracts.costs import CURRENCY

router = APIRouter(prefix="/v1/admin/usage", tags=["usage"])
ReposDep = Annotated[Repos, Depends(get_repos)]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Buckets(_Out):
    llm_micros: int  # Chat & decisions
    image_micros: int  # Image generation
    video_micros: int  # Video generation
    total_micros: int


class Purposes(_Out):
    """The same money by purpose (plan/2026-11-23b); the three add up to the bucket total."""

    production_setup_micros: int  # canon, character and look sheets
    episode_setup_micros: int  # reading documents, the build, Shot Planner Raphael
    scene_micros: int  # design, Camera, prompts, frames, video, chat


class ProductionSpend(Buckets):
    production_id: UUID | None  # None = calls tied to no production (and calls of a deleted one)
    name: str | None
    purpose: Purposes


class Unpriced(_Out):
    what: str  # the model or video size with no price
    bucket: Literal["llm", "image", "video"]
    count: int  # calls or renders left out of the figures


class MonthSpend(_Out):
    currency: str = CURRENCY
    month: str  # "2026-11"
    as_of: datetime
    total: Buckets
    purpose: Purposes
    productions: list[ProductionSpend]
    missing: list[Unpriced]
    complete: bool  # false = something had no price, so the figures leave it out


def _buckets(t: ut.BucketTotals) -> dict[str, int]:
    return {"llm_micros": t.llm, "image_micros": t.image, "video_micros": t.video, "total_micros": t.total}


def _purposes(p: PurposeTotals | None) -> Purposes:
    p = p or PurposeTotals()
    return Purposes(production_setup_micros=p.production_setup, episode_setup_micros=p.episode_setup,
                    scene_micros=p.scene)


@router.get("", response_model=MonthSpend)
async def get_month_spend(_: Admin, repos: ReposDep,
                          month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None) -> MonthSpend:
    try:
        label, usage = await svc.month_usage(repos, month)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    names = {str(p["id"]): str(p.get("title") or "") for p in await repos.productions.list_all()}
    rows = []
    for pid, totals in ut.rows_by_production(usage):
        known = pid in names
        rows.append(ProductionSpend(production_id=UUID(pid) if known else None, name=names.get(pid),
                                    purpose=_purposes(usage.purposes.get(pid)), **_buckets(totals)))
    # A production that was deleted is folded into the "no production" row (its id names nothing any more).
    merged: list[ProductionSpend] = [r for r in rows if r.production_id is not None]
    loose = [r for r in rows if r.production_id is None]
    if loose:
        merged.append(ProductionSpend(production_id=None, name=None,
                                      purpose=Purposes(
                                          production_setup_micros=sum(r.purpose.production_setup_micros for r in loose),
                                          episode_setup_micros=sum(r.purpose.episode_setup_micros for r in loose),
                                          scene_micros=sum(r.purpose.scene_micros for r in loose)),
                                      llm_micros=sum(r.llm_micros for r in loose),
                                      image_micros=sum(r.image_micros for r in loose),
                                      video_micros=sum(r.video_micros for r in loose),
                                      total_micros=sum(r.total_micros for r in loose)))
    missing = [Unpriced(what=what, bucket=bucket, count=n) for what, bucket, n in ut.by_bucket(usage.missing)]
    return MonthSpend(month=label, as_of=datetime.now(UTC), total=Buckets(**_buckets(usage.total)),
                      purpose=_purposes(usage.purpose),
                      productions=merged, missing=missing, complete=not missing)
