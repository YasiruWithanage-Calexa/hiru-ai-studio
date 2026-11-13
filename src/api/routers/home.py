"""A production's documents page in one request (plan/2026-11-13d phase 4, F9).

After "Create and upload" the person lands on the documents page, which asked for the production, the caller's
access, the documents and the director board separately (with `/overview` from the layout, `/me` and `/usage` from the
header, nine GETs at once). This answers the four page reads at once by calling the same functions their own routes
call, so each part equals its single route's answer (`tests/api/test_home.py`). The single routes stay.
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
from api.routers import director, documents, productions
from api.schemas import MyAccess
from contracts.production import Production
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["home"])


class ProductionHome(BaseModel):
    production: Production  # = GET /v1/productions/{id}
    access: MyAccess  # = GET .../access
    documents: list[documents.DocumentOut]  # = GET .../documents
    board: director.BoardView  # = GET .../director-board (its members carry their personas)


@router.get("/home", response_model=ProductionHome)
async def get_home(production_id: UUID,
                   access: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                   repos: Annotated[Repos, Depends(get_repos)]) -> ProductionHome:
    docs, board = await asyncio.gather(documents.list_documents(production_id, access, repos),
                                       director.get_board(production_id, access, repos))
    return ProductionHome(production=await productions.get_production(production_id, access, repos),
                          access=await productions.my_access(access), documents=docs, board=board)
