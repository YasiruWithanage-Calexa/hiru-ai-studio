"""Scene looks (screen 1, the Director panel's Canon tab): which look of a character a scene uses.

* A character has many looks (`routers/looks.py`), each for a stretch of episodes. Without a pick,
  a scene follows the episode rule: the narrowest ready look that covers its episode.
* A person can pick one look for one scene instead. Only a ready look can be picked: a draft never
  applies. Deleting the pick goes back to the episode rule.
* Making and changing looks is not done here; it stays on the canon entity page.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from contracts.canon import CanonKind, SceneLook, SceneLookChoice, SceneLooksView
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}/scenes/{scene_id}/looks", tags=["looks"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanEdit = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]


async def _scene(repos: Repos, production_id: UUID, scene_id: UUID) -> None:
    if await repos.scenes.get(production_id, scene_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")


@router.get("", response_model=SceneLooksView)
async def list_scene_looks(production_id: UUID, scene_id: UUID, _: CanView, repos: ReposDep) -> SceneLooksView:
    await _scene(repos, production_id, scene_id)
    return SceneLooksView(looks=[SceneLook.model_validate(r) for r in await repos.scene_looks.list(scene_id)])


@router.put("/{entity_id}", response_model=SceneLook)
async def choose_scene_look(production_id: UUID, scene_id: UUID, entity_id: UUID, body: SceneLookChoice,
                            access: CanEdit, repos: ReposDep) -> SceneLook:
    await _scene(repos, production_id, scene_id)
    entity = await repos.canon.get(production_id, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Canon item not found.")
    if entity["kind"] != CanonKind.CHARACTER.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only characters have looks.")
    look = await repos.looks.get(entity_id, body.look_id)
    if look is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Look not found.")
    if look.get("status") != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a ready look can be used in a scene.")
    row = await repos.scene_looks.choose({
        "scene_id": str(scene_id), "entity_id": str(entity_id), "look_id": str(body.look_id),
        "production_id": str(production_id), "chosen_by": str(access.user.id)})
    await repos.audit.record(action="scene.look_choose", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"character": entity["name"], "look": look["name"]})
    return SceneLook.model_validate(row)


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_scene_look(production_id: UUID, scene_id: UUID, entity_id: UUID, access: CanEdit,
                           repos: ReposDep) -> Response:
    """Back to the episode rule for this character in this scene."""
    await _scene(repos, production_id, scene_id)
    await repos.scene_looks.clear(scene_id, entity_id)
    await repos.audit.record(action="scene.look_clear", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"character": str(entity_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
