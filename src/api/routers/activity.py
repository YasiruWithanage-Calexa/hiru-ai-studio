"""Who changed what on a production, newest first (the audit log, PLAN.md §6.2 "every agent change
attributed"). A person sees the production's own entries only; names, never e-mail addresses."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["activity"])


class ActivityEntry(BaseModel):
    id: int
    at: datetime
    action: str  # "frame.accept", "scene.director_edit" ...
    entity: str
    entity_id: str | None
    actor_name: str  # the person, or the person an agent acted for
    actor_agent: str | None  # "director_chat", "shot_producer" ... when an agent made the change
    diff: dict[str, Any]


@router.get("/activity", response_model=list[ActivityEntry])
async def list_activity(production_id: UUID,
                        _: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                        repos: Annotated[Repos, Depends(get_repos)],
                        limit: Annotated[int, Query(ge=1, le=300)] = 100) -> list[ActivityEntry]:
    rows = await repos.audit.list(production_id, limit)
    names = {str(p["id"]): str(p.get("display_name") or "") for p in await repos.profiles.list()}
    return [ActivityEntry(id=int(r["id"]), at=r["created_at"], action=str(r["action"]), entity=str(r["entity"]),
                          entity_id=r.get("entity_id"), actor_name=names.get(str(r.get("actor_user_id")), "Someone"),
                          actor_agent=r.get("actor_agent"), diff=r.get("diff") or {})
            for r in rows]
