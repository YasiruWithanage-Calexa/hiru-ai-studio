"""Looks (screen 1, the canon entity page): what a character wears for a stretch of episodes.

* A character has ONE base sheet (the entity's reference sheet, `routers/canon.py`) and many looks.
  A look sheet is painted from the base sheet (`frame_render`), so the face and body stay the same
  and only clothes, hair, makeup and accessories change.
* A person writes the look; the sheet is made on request and a person marks the look ready once
  they have seen it. Changing the wardrobe of a ready look sends it back to draft: its sheet no
  longer matches the words.
* Nothing here is derived from the card: a look is a person's wording, kept as they wrote it.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import media_links
from api.workers import task_manager
from contracts.canon import CanonKind, CanonLook, EpisodeRange, LookCreate, LooksView, LookUpdate, name_key
from contracts.jobs import JobKind
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}/canon/{entity_id}/looks", tags=["looks"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanEdit = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]

_WARDROBE = ("outfit", "hair", "makeup", "accessories")


class SheetStarted(BaseModel):
    job_id: UUID


def _asset_path(assets: object) -> str:
    first = assets[0] if isinstance(assets, list) and assets else None
    path = first.get("path") if isinstance(first, dict) else first
    return str(path or "")


def _look(row: Row) -> CanonLook:
    path = _asset_path(row.get("sheet_assets"))
    return CanonLook.model_validate({**row, "sheet_url": media_links.url("references", path) if path else ""})


def _ranges(ranges: list[EpisodeRange]) -> list[dict[str, int]]:
    return [r.model_dump(by_alias=True) for r in ranges]


async def _character(repos: Repos, production_id: UUID, entity_id: UUID) -> Row:
    row = await repos.canon.get(production_id, entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Canon item not found.")
    if row["kind"] != CanonKind.CHARACTER.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only characters have looks.")
    return row


async def _get(repos: Repos, entity_id: UUID, look_id: UUID) -> Row:
    row = await repos.looks.get(entity_id, look_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Look not found.")
    return row


async def _unique_name(repos: Repos, entity_id: UUID, name: str, own_id: str | None = None) -> None:
    clash = [r for r in await repos.looks.list(entity_id)
             if str(r["id"]) != own_id and name_key(r["name"]) == name_key(name)]
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, "This character already has a look with this name.")


@router.get("", response_model=LooksView)
async def list_looks(production_id: UUID, entity_id: UUID, _: CanView, repos: ReposDep) -> LooksView:
    await _character(repos, production_id, entity_id)
    episodes = await repos.episodes.list(production_id)
    return LooksView(episode_count=len(episodes), looks=[_look(r) for r in await repos.looks.list(entity_id)])


@router.post("", response_model=CanonLook, status_code=status.HTTP_201_CREATED)
async def create_look(production_id: UUID, entity_id: UUID, body: LookCreate, access: CanEdit,
                      repos: ReposDep) -> CanonLook:
    await _character(repos, production_id, entity_id)
    name = " ".join(body.name.split())
    await _unique_name(repos, entity_id, name)
    row = await repos.looks.create({
        "entity_id": str(entity_id), "production_id": str(production_id), "name": name,
        "ranges": _ranges(body.ranges), "outfit": body.outfit.strip(), "hair": body.hair.strip(),
        "makeup": body.makeup.strip(), "accessories": body.accessories.strip(), "created_by": str(access.user.id)})
    await repos.audit.record(action="canon.look_create", entity="canon_look", entity_id=str(row["id"]),
                             actor_user_id=access.user.id, production_id=production_id, diff={"name": name})
    return _look(row)


@router.patch("/{look_id}", response_model=CanonLook)
async def update_look(production_id: UUID, entity_id: UUID, look_id: UUID, body: LookUpdate, access: CanEdit,
                      repos: ReposDep) -> CanonLook:
    await _character(repos, production_id, entity_id)
    row = await _get(repos, entity_id, look_id)
    fields: Row = {k: v for k, v in body.model_dump(exclude_unset=True, exclude={"ranges"}).items() if v is not None}
    if body.ranges is not None:
        fields["ranges"] = _ranges(body.ranges)
    if "name" in fields:
        fields["name"] = " ".join(str(fields["name"]).split())
        await _unique_name(repos, entity_id, fields["name"], str(look_id))
    for key in _WARDROBE:
        if key in fields:
            fields[key] = str(fields[key]).strip()
    fields = {k: v for k, v in fields.items() if row.get(k) != v}
    if not fields:
        return _look(row)
    if row.get("status") == "ready" and any(k in fields for k in _WARDROBE):
        fields["status"] = "draft"  # the sheet no longer matches the words
    updated = await repos.looks.update(look_id, fields)
    await repos.audit.record(action="canon.look_update", entity="canon_look", entity_id=str(look_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={k: [row.get(k), v] for k, v in fields.items() if k != "status"})
    return _look(updated)


@router.delete("/{look_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_look(production_id: UUID, entity_id: UUID, look_id: UUID, access: CanEdit,
                      repos: ReposDep) -> Response:
    await _character(repos, production_id, entity_id)
    row = await _get(repos, entity_id, look_id)
    await repos.looks.delete(look_id)
    await repos.audit.record(action="canon.look_delete", entity="canon_look", entity_id=str(look_id),
                             actor_user_id=access.user.id, production_id=production_id, diff={"name": row["name"]})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{look_id}/sheet", response_model=SheetStarted, status_code=status.HTTP_202_ACCEPTED)
async def make_look_sheet(production_id: UUID, entity_id: UUID, look_id: UUID, access: CanEdit,
                          repos: ReposDep) -> SheetStarted:
    """Paint the look sheet from the character's base sheet (`frame_render`). The base sheet is
    the only picture sent; the clothes, hair, makeup and accessories are the look's words."""
    entity = await _character(repos, production_id, entity_id)
    row = await _get(repos, entity_id, look_id)
    if not _asset_path((entity.get("current") or {}).get("reference_assets")):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Paint {entity['name']}'s base sheet first.")
    if not any(str(row.get(k) or "").strip() for k in _WARDROBE):
        raise HTTPException(status.HTTP_409_CONFLICT, "Describe what they wear first.")
    job_id = await task_manager.dispatch(JobKind.FRAME_RENDER, repos, actor_user_id=access.user.id,
                                         production_id=production_id, request={"look_id": str(look_id)},
                                         state={"look_id": str(look_id)})
    await repos.audit.record(action="canon.look_sheet", entity="canon_look", entity_id=str(look_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"job_id": str(job_id)})
    return SheetStarted(job_id=job_id)


@router.post("/{look_id}/ready", response_model=CanonLook)
async def mark_ready(production_id: UUID, entity_id: UUID, look_id: UUID, access: CanEdit,
                     repos: ReposDep) -> CanonLook:
    """A person has seen the sheet and it is right. Only a look with a sheet can be ready."""
    await _character(repos, production_id, entity_id)
    row = await _get(repos, entity_id, look_id)
    if not _asset_path(row.get("sheet_assets")):
        raise HTTPException(status.HTTP_409_CONFLICT, "Make the look sheet first.")
    return await _set_status(repos, access, production_id, row, "ready")


@router.post("/{look_id}/draft", response_model=CanonLook)
async def mark_draft(production_id: UUID, entity_id: UUID, look_id: UUID, access: CanEdit,
                     repos: ReposDep) -> CanonLook:
    await _character(repos, production_id, entity_id)
    return await _set_status(repos, access, production_id, await _get(repos, entity_id, look_id), "draft")


async def _set_status(repos: Repos, access: ProductionAccess, production_id: UUID, row: Row, to: str) -> CanonLook:
    if row.get("status") == to:
        return _look(row)
    updated = await repos.looks.update(UUID(str(row["id"])), {"status": to})
    await repos.audit.record(action=f"canon.look_{to}", entity="canon_look", entity_id=str(row["id"]),
                             actor_user_id=access.user.id, production_id=production_id, diff={"name": row["name"]})
    return _look(updated)
