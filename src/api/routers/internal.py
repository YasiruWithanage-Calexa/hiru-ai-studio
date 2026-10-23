"""Function → API callbacks. Not for browsers: every call carries `X-Internal-Secret`
(`API__INTERNAL_SECRET`, shared with the functions through Secret Manager).

`POST /internal/pipeline/advance` is the courier (PLAN.md §10): a function finished hop `cursor`
of a multi-hop job and hands over the state for the next. It is idempotent: a re-delivered
callback finds the cursor already moved and does nothing.
"""
from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from api.config import get_settings
from api.deps.db import get_repos
from api.repositories import Repos
from api.workers import task_manager
from contracts.jobs import AdvanceRequest

router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)


def require_internal(x_internal_secret: Annotated[str, Header()] = "") -> None:
    expected = get_settings().api.internal_secret.get_secret_value()
    if not expected or not hmac.compare_digest(x_internal_secret.encode(), expected.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden.")


class Advanced(BaseModel):
    advanced: bool


@router.post("/pipeline/advance", response_model=Advanced, dependencies=[Depends(require_internal)])
async def advance(body: AdvanceRequest, repos: Annotated[Repos, Depends(get_repos)]) -> Advanced:
    job = await repos.jobs.get(body.job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")
    return Advanced(advanced=await task_manager.advance(repos, job, body.cursor, body.state, again=body.again))
