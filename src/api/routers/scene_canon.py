"""Scene canon (screen 1, the Director panel's Canon tab): who and what a scene uses.

* The script decides the natural cast of every shot: its speakers, who its action names, the
  scene's place. A person adds or takes out canon for the WHOLE scene here; it is written to each
  shot's `person_edits.cast`, the same marks the director chat makes one shot at a time. Frames,
  prompts and the stale check read them from there, so nothing else needs to know about this route.
* Like the chat, a mark is stored only when it differs from the script: adding what a shot already
  has, or taking out what it never had, stores nothing. Adding canon the script already uses (it was
  taken out before) brings it back in the shots it was taken out of; adding canon the script never
  uses puts it in every shot.
* An APPROVED scene is locked: unapprove it first.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.routers.scenes import SceneView, _editable, load, natural_cast, view
from contracts.producer import PersonEdits
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}/scenes/{scene_id}/canon", tags=["scenes"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanEdit = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]


async def _set_in_scene(repos: Repos, access: ProductionAccess, scene_id: UUID, entity_id: UUID, *,
                        add: bool) -> SceneView:
    production_id = access.production_id
    ld = await load(repos, access, scene_id)
    entity = await repos.canon.get(production_id, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Canon item not found.")
    _editable(ld.scene)
    if not ld.shots:
        raise HTTPException(status.HTTP_409_CONFLICT, "A scene needs shots before its canon can be changed.")
    eid = str(entity_id)
    natural = natural_cast(ld, await repos.canon.list(production_id))
    in_script = any(eid in cast for cast in natural.values())
    changed = 0
    for shot in ld.shots:
        edits = PersonEdits.of(shot)
        cast = edits.cast
        before = (list(cast.add), list(cast.remove))
        if add:
            # What the script already uses comes back where it was taken out; only canon the script
            # never uses is put into every shot.
            cast.remove = [i for i in cast.remove if i != eid]
            if not in_script and eid not in cast.add:
                cast.add.append(eid)
        else:
            cast.add = [i for i in cast.add if i != eid]
            if eid in natural[str(shot["id"])] and eid not in cast.remove:
                cast.remove.append(eid)
        if (cast.add, cast.remove) != before:
            await repos.shots.update(UUID(str(shot["id"])), {"person_edits": edits.dump()})
            changed += 1
    if changed:
        await repos.audit.record(action="scene.canon_add" if add else "scene.canon_remove", entity="scene",
                                 entity_id=str(scene_id), actor_user_id=access.user.id,
                                 production_id=production_id, diff={"canon": entity["name"], "shots": changed})
    return await view(repos, access, scene_id)


@router.put("/{entity_id}", response_model=SceneView)
async def add_scene_canon(production_id: UUID, scene_id: UUID, entity_id: UUID, access: CanEdit,
                          repos: ReposDep) -> SceneView:
    """Put this canon item in the scene: every shot, or back where it was taken out."""
    return await _set_in_scene(repos, access, scene_id, entity_id, add=True)


@router.delete("/{entity_id}", response_model=SceneView)
async def remove_scene_canon(production_id: UUID, scene_id: UUID, entity_id: UUID, access: CanEdit,
                             repos: ReposDep) -> SceneView:
    """Take this canon item out of every shot of the scene (its place too)."""
    return await _set_in_scene(repos, access, scene_id, entity_id, add=False)
