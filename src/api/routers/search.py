"""Search a production's documents (and optionally the craft corpus), and look up craft
techniques by the effect they should have on the viewer."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from api.deps.auth import User
from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.services import retrieval
from api.services.ai import AI, UsageContext, get_ai
from contracts.documents import SearchRequest, SearchResponse
from contracts.roles import Permission

router = APIRouter(tags=["search"])
ReposDep = Annotated[Repos, Depends(get_repos)]
AIDep = Annotated[AI, Depends(get_ai)]


@router.post("/v1/productions/{production_id}/search", response_model=SearchResponse)
async def search_production(production_id: UUID, body: SearchRequest,
                            access: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                            repos: ReposDep, ai: AIDep) -> SearchResponse:
    return await retrieval.search(repos, ai, production_id=production_id,
                                  actor_user_id=access.user.id, req=body)


class TechniqueQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=1000)  # the intended effect, e.g. "she feels trapped"
    domain: str = "camera"
    categories: list[str] | None = None  # optional hint ("Camera Angle"); unknown ones are ignored
    k: int = Field(default=5, ge=1, le=20)


class Technique(BaseModel):
    category: str
    name: str
    abbreviation: str
    definition: str
    use_case: str
    example_film: str
    score: float


@router.post("/v1/craft/techniques/search", response_model=list[Technique])
async def search_techniques(body: TechniqueQuery, user: User, repos: ReposDep, ai: AIDep) -> list[Technique]:
    embedding = await ai.embed_query(body.query, UsageContext(repos, user.id, None))
    rows = await repos.search.match_techniques(query_text=body.query, query_embedding=embedding,
                                               domain=body.domain, categories=body.categories,
                                               match_count=body.k)
    return [Technique.model_validate(r) for r in rows]
