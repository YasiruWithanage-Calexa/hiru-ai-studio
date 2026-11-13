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
from api.repositories import Repos, Row
from api.routers import looks, production, scenes, structure
from api.schemas import MyAccess
from contracts.canon import CanonKind, LooksView, SceneLook, SceneLooksView
from contracts.director import ChatMessage, ChatThread
from contracts.production import ProductionSettings
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["page"])


class ScenePage(BaseModel):
    view: scenes.SceneView
    production: production.SceneProductionView
    episode: structure.EpisodeDetail
    access: MyAccess
    threads: list[ChatThread]
    messages: list[ChatMessage]  # the first thread's, which is the scene's main chat
    # plan/2026-11-13b phase 2: the production's planner, and the planners whose column holds a plan for this scene
    # (computed from the scene row already read), so the page asks only for the panels that can show something.
    shot_planner: str = "classic"
    planners_with_plans: list[str] = []
    # Phase 3: the looks of each character the scene uses (canon entity id -> looks) and the scene's own picks.
    cast_looks: dict[str, LooksView] = {}
    scene_looks: SceneLooksView = SceneLooksView(looks=[])


PLANNER_COLUMNS = ("adam", "david", "jonathan", "raphael")


def planners_with_plans(scene: dict[str, object]) -> list[str]:
    """Planner columns that hold a plan written by that planner (the same test each planner's route uses)."""
    return [n for n in PLANNER_COLUMNS if isinstance(raw := scene.get(n), dict) and raw.get("planner") == n]


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
    settings = ProductionSettings.model_validate(access.production.get("settings") or {})
    characters = {str(c.id) for c in view.canon if c.kind == CanonKind.CHARACTER}
    all_looks: list[Row] = []
    picks: list[Row] = []
    episodes: list[Row] = []
    if characters:  # both reads are already in this request's memo (production.load)
        all_looks, picks, episodes = await asyncio.gather(
            repos.looks.list_for_production(production_id), repos.scene_looks.list(scene_id),
            repos.episodes.list(production_id))
    return ScenePage(view=view,
                     shot_planner=str(settings.shot_planner), planners_with_plans=planners_with_plans(ld.scene),
                     cast_looks={cid: LooksView(episode_count=len(episodes),
                                                looks=[looks.look_view(r) for r in all_looks
                                                       if str(r["entity_id"]) == cid]) for cid in characters},
                     scene_looks=SceneLooksView(looks=[SceneLook.model_validate(r) for r in picks
                                                       if str(r["entity_id"]) in characters]),
                     production=production.scene_view(ld), episode=episode,
                     access=MyAccess(role=access.role, permissions=sorted(access.permissions)),
                     threads=[ChatThread.model_validate(t) for t in mine],
                     messages=[ChatMessage.model_validate(m) for m in rows])
