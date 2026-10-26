"""Monthly usage as a percentage. Never tokens, credits or money in what a member sees
(CLAUDE.md, PLAN.md §10).

The month's budget is set by an admin (`usage_budget`, PLAN.md §13 step 21); with none set, the
`USAGE__MONTHLY_TOKEN_BUDGET` setting applies. Model tokens include images (frame_render records
the image model's tokens like any other call).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.config import get_settings
from api.deps.auth import User
from api.deps.authz import Admin
from api.deps.db import get_repos
from api.repositories import Repos

router = APIRouter(prefix="/v1/usage", tags=["usage"])
ReposDep = Annotated[Repos, Depends(get_repos)]


class Usage(BaseModel):
    percent: int = Field(ge=0, le=100)


class Budget(BaseModel):
    """Admin only: the month's budget in model tokens, and where it comes from."""

    month: str  # "2026-10-01"
    budget_tokens: int = Field(gt=0)
    source: str = "setting"  # "budget" when an admin set it for this month


class BudgetUpdate(BaseModel):
    budget_tokens: int = Field(gt=0, le=10_000_000_000)


def _month() -> tuple[datetime, str]:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, start.date().isoformat()


async def _budget(repos: Repos, month: str) -> Budget:
    tokens = await repos.usage.budget(month)
    if tokens:
        return Budget(month=month, budget_tokens=tokens, source="budget")
    return Budget(month=month, budget_tokens=max(get_settings().usage.monthly_token_budget, 1))


@router.get("", response_model=Usage)
async def get_usage(_: User, repos: ReposDep) -> Usage:
    start, month = _month()
    used, budget = await asyncio.gather(repos.usage.tokens_since(start), _budget(repos, month))
    return Usage(percent=min(100, round(100 * used / budget.budget_tokens)))


@router.get("/budget", response_model=Budget)
async def get_budget(_: Admin, repos: ReposDep) -> Budget:
    return await _budget(repos, _month()[1])


@router.put("/budget", response_model=Budget)
async def set_budget(body: BudgetUpdate, admin: Admin, repos: ReposDep) -> Budget:
    month = _month()[1]
    await repos.usage.set_budget(month, body.budget_tokens, admin.id)
    await repos.audit.record(action="usage.budget", entity="usage_budget", entity_id=month, actor_user_id=admin.id,
                             diff={"budget_tokens": body.budget_tokens})
    return await _budget(repos, month)
