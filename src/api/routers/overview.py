"""One read for the production chrome every studio screen draws: the production, its structure
(episodes → scenes, shot counts), its canon and how many questions are open.

A Backend-for-Frontend endpoint: the header, sidebar and overview each needed a slice of this,
and fetching the slices separately cost one auth check and one copy of the shot/scene reads per
slice. Here they share one access check and one read of each table.
"""
from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.routers.canon import _entity
from api.routers.productions import _production
from api.routers.structure import Structure, structure_of
from contracts.build import QuestionStatus
from contracts.canon import CanonEntity
from contracts.production import Production
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["overview"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]


class Overview(BaseModel):
    production: Production
    structure: Structure
    canon: list[CanonEntity]
    open_questions: int


@router.get("/overview", response_model=Overview)
async def get_overview(production_id: UUID, access: CanView, repos: ReposDep) -> Overview:
    episodes, scenes, shots, canon, open_q = await asyncio.gather(
        repos.episodes.list(production_id), repos.scenes.list(production_id), repos.shots.list(production_id),
        repos.canon.list(production_id), repos.questions.list(production_id, QuestionStatus.OPEN.value))
    return Overview(production=_production(access.production, access.role),
                    structure=structure_of(episodes, scenes, shots, canon),
                    canon=[_entity(r) for r in canon], open_questions=len(open_q))
