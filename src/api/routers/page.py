"""One read for the shot page (plan/2026-11-08c phase 4).

The page used to make five calls: the scene (Director's view), its production view, its episode, its threads and the
main thread's messages. Each one resolved access again and loaded the scene on its own. This answers all five in one
request, by calling the same functions the five routes call, so the two can never disagree. The five routes stay: the
interface still uses them for single re-reads.
"""
from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.routers import production, scenes, structure
from api.schemas import MyAccess
from contracts.director import ChatMessage, ChatThread
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["page"])


class ScenePage(BaseModel):
    view: scenes.SceneView
    production: production.SceneProductionView
    episode: structure.EpisodeDetail
    access: MyAccess
    threads: list[ChatThread]
    messages: list[ChatMessage]  # the first thread's, which is the scene's main chat


@router.get("/scenes/{scene_id}/page", response_model=ScenePage)
async def get_scene_page(production_id: UUID, scene_id: UUID,
                         access: Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))],
                         repos: Annotated[Repos, Depends(get_repos)]) -> ScenePage:
    ld = await production.load(repos, access, scene_id)  # 404 for a scene that is not here
    episode_id = UUID(str(ld.scene["episode_id"]))
    view, episode, threads = await asyncio.gather(
        scenes.view(repos, access, scene_id), structure.get_episode(production_id, episode_id, access, repos),
        repos.threads.list(production_id, scene_id))
    mine = [t for t in threads if t.get("chat", "scene") == "scene"]
    rows = await repos.messages.list(mine[0]["id"]) if mine else []
    if not ld.states:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This scene has no shots yet.")
    return ScenePage(view=view, production=production.scene_view(ld), episode=episode,
                     access=MyAccess(role=access.role, permissions=sorted(access.permissions)),
                     threads=[ChatThread.model_validate(t) for t in mine],
                     messages=[ChatMessage.model_validate(m) for m in rows])
