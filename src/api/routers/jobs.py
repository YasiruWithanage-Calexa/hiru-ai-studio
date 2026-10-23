"""Jobs: read one, read its events, and (admin) start an echo job to test the dispatch path.

The browser normally follows a job through Supabase Realtime on `job_events`; `GET .../events`
is the catch-up read for a page opened after the job started.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.deps.auth import CurrentUser, User
from api.deps.authz import Admin, resolve_access
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.workers import task_manager
from contracts.jobs import Job, JobEvent, JobKind
from contracts.roles import Permission

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])
ReposDep = Annotated[Repos, Depends(get_repos)]
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")


async def _visible_job(job_id: UUID, user: CurrentUser, repos: Repos) -> Row:
    row = await repos.jobs.get(job_id)
    if row is None:
        raise _NOT_FOUND
    if user.is_admin or row.get("requested_by") == str(user.id):
        return row
    if row.get("production_id"):
        try:
            access = await resolve_access(user, UUID(row["production_id"]), repos)
        except HTTPException:
            raise _NOT_FOUND from None
        if Permission.VIEW in access.permissions:
            return row
    raise _NOT_FOUND


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: UUID, user: User, repos: ReposDep) -> Job:
    return Job.model_validate(await _visible_job(job_id, user, repos))


@router.get("/{job_id}/events", response_model=list[JobEvent])
async def get_job_events(job_id: UUID, user: User, repos: ReposDep,
                         after: Annotated[int, Query(ge=0)] = 0) -> list[JobEvent]:
    await _visible_job(job_id, user, repos)
    return [JobEvent.model_validate(r) for r in await repos.jobs.events(job_id, after)]


class EchoRequest(BaseModel):
    message: str = "ping"


class Dispatched(BaseModel):
    job_id: UUID


@router.post("/echo", response_model=Dispatched, status_code=status.HTTP_202_ACCEPTED)
async def start_echo(body: EchoRequest, admin: Admin, repos: ReposDep) -> Dispatched:
    """Smoke test of API → queue → function → job_events → Realtime. Admin only."""
    job_id = await task_manager.dispatch(JobKind.ECHO, repos, actor_user_id=admin.id,
                                         request=body.model_dump(),
                                         state={"message": body.message})
    return Dispatched(job_id=job_id)
