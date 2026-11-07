"""A scene's production cost, and the price list behind it (plan/2026-11-06d §6).

    GET  /v1/productions/{pid}/scenes/{sid}/cost   ONE figure: the scene's total in USD (VIEW_COSTS only)
    GET  /v1/prices                                 admin: the dated price list
    PUT  /v1/prices                                 admin: add a price that applies from a date (never edits a row)

The scene cost answers with the total and two flags, nothing else: no lines, no rates, no margins, so a breakdown
cannot leak through the network tab. A production the caller cannot see is 404; a member without `VIEW_COSTS` is 403.
`/v1/usage` stays a percentage; this does not add a monthly bill.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from api.deps.authz import Admin, ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.routers.production import load
from api.services import costs as svc
from contracts.costs import CURRENCY, Price
from contracts.roles import Permission

router = APIRouter(tags=["costs"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanSeeCosts = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW_COSTS))]


class SceneCost(BaseModel):
    """The whole response. There is deliberately no field for a part, a rate or a margin."""

    model_config = ConfigDict(extra="forbid")

    currency: str = CURRENCY
    total_micros: int
    designed: bool  # false = before "Recommend settings for all shots": the figure will move
    complete: bool  # false = a price is missing, so the figure leaves that item out


@router.get("/v1/productions/{production_id}/scenes/{scene_id}/cost", response_model=SceneCost)
async def get_scene_cost(production_id: UUID, scene_id: UUID, access: CanSeeCosts, repos: ReposDep) -> SceneCost:
    ld = await load(repos, access, scene_id)
    total = await svc.scene_cost(repos, ld)
    return SceneCost(total_micros=total.total_micros, designed=svc.designed(ld), complete=total.complete)


# ── the price list (admin) ────────────────────────────────────────────────────────────────────


class PriceOut(Price):
    id: UUID
    set_by: UUID | None = None


class PriceIn(Price):
    """A new price. `valid_from` defaults to now and cannot be in the past: a price applies to new work only, and old
    spending keeps the price it was made at."""


@router.get("/v1/prices", response_model=list[PriceOut])
async def list_prices(_: Admin, repos: ReposDep) -> list[PriceOut]:
    return [PriceOut.model_validate({k: v for k, v in r.items() if k in PriceOut.model_fields})
            for r in await repos.costs.prices()]


@router.put("/v1/prices", response_model=PriceOut, status_code=status.HTTP_201_CREATED)
async def add_price(body: PriceIn, admin: Admin, repos: ReposDep) -> PriceOut:
    now = datetime.now(UTC)
    fields = body.model_fields_set
    when = body.valid_from if "valid_from" in fields else now
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if when < now - timedelta(minutes=5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "A price applies from now on. Work already made keeps the price it was made at.")
    if body.kind == "tokens" and not body.model_prefix:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name the model this price is for.")
    if body.kind == "video_second" and not (body.engine and body.resolution):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name the video model and the size.")
    if body.kind == "estimate" and body.model_prefix not in ("frame", "prompt"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An estimate is for a frame or a prompt.")
    row = {**body.model_dump(mode="json"), "valid_from": when.isoformat(), "set_by": str(admin.id)}
    saved = await repos.costs.add_price(row)
    await repos.audit.record(action="prices.add", entity="prices", entity_id=str(saved["id"]), actor_user_id=admin.id,
                             diff={"kind": body.kind, "model_prefix": body.model_prefix, "engine": body.engine,
                                   "resolution": body.resolution, "valid_from": when.isoformat()})
    return PriceOut.model_validate({k: v for k, v in saved.items() if k in PriceOut.model_fields})
