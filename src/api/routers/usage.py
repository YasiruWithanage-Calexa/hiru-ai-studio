"""Monthly usage as a percentage. Never tokens, credits or money (CLAUDE.md, PLAN.md §10)."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.config import get_settings
from api.deps.auth import User
from api.deps.db import get_repos
from api.repositories import Repos

router = APIRouter(prefix="/v1/usage", tags=["usage"])


class Usage(BaseModel):
    percent: int = Field(ge=0, le=100)


@router.get("", response_model=Usage)
async def get_usage(_: User, repos: Annotated[Repos, Depends(get_repos)]) -> Usage:
    now = datetime.now(UTC)
    used = await repos.usage.tokens_since(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    budget = max(get_settings().usage.monthly_token_budget, 1)
    return Usage(percent=min(100, round(100 * used / budget)))
