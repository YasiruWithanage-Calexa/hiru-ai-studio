"""The canon library (screen 1): characters, locations and props with versioned cards.

* A person's change to a card is a NEW VERSION (`source: user`), never an edit in place, so a
  shot written against version 3 can say so and be flagged when version 4 appears.
* LOCKED means approved: engines leave it alone, and people must unlock it before changing it.
* The voice pin and wardrobe anchor are derived from the card unless a person writes them.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from contracts.canon import (
    CanonEntity,
    CanonEntityUpdate,
    CanonKind,
    CanonVersion,
    CanonVersionCreate,
    name_key,
    reference_sheet_prompt,
    voice_pin,
    wardrobe_anchor,
)
from contracts.roles import Permission
from contracts.veo import ASPECT_RATIO, Orientation

router = APIRouter(prefix="/v1/productions/{production_id}/canon", tags=["canon"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanEdit = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]


class CanonDetail(CanonEntity):
    versions: list[CanonVersion]


def _entity(row: Row) -> CanonEntity:
    current = row.get("current")
    return CanonEntity.model_validate({**row, "current": current,
                                       "current_version": current["version"] if current else None})


async def _get(repos: Repos, production_id: UUID, entity_id: UUID) -> Row:
    row = await repos.canon.get(production_id, entity_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Canon item not found.")
    return row


def _unlocked(row: Row) -> None:
    if row.get("locked"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This item is locked. Unlock it before changing it.")


@router.get("", response_model=list[CanonEntity])
async def list_canon(production_id: UUID, _: CanView, repos: ReposDep,
                     kind: CanonKind | None = None) -> list[CanonEntity]:
    rows = await repos.canon.list(production_id)
    return [_entity(r) for r in rows if kind is None or r["kind"] == kind]


@router.get("/{entity_id}", response_model=CanonDetail)
async def get_canon(production_id: UUID, entity_id: UUID, _: CanView, repos: ReposDep) -> CanonDetail:
    row = await _get(repos, production_id, entity_id)
    versions = [CanonVersion.model_validate(v) for v in await repos.canon.versions(entity_id)]
    return CanonDetail(**_entity(row).model_dump(), versions=versions)


@router.patch("/{entity_id}", response_model=CanonEntity)
async def update_canon(production_id: UUID, entity_id: UUID, body: CanonEntityUpdate, access: CanEdit,
                       repos: ReposDep) -> CanonEntity:
    row = await _get(repos, production_id, entity_id)
    _unlocked(row)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        clash = [r for r in await repos.canon.list(production_id)
                 if r["kind"] == row["kind"] and str(r["id"]) != str(entity_id)
                 and name_key(r["name"]) == name_key(fields["name"])]
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{clash[0]['code']} already has this name.")
    if not fields:
        return _entity(row)
    await repos.canon.update(entity_id, fields)
    await repos.audit.record(action="canon.update", entity="canon_entity", entity_id=str(entity_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={k: [row.get(k), v] for k, v in fields.items()})
    return _entity(await _get(repos, production_id, entity_id))


@router.post("/{entity_id}/versions", response_model=CanonVersion, status_code=status.HTTP_201_CREATED)
async def add_canon_version(production_id: UUID, entity_id: UUID, body: CanonVersionCreate, access: CanEdit,
                            repos: ReposDep) -> CanonVersion:
    row = await _get(repos, production_id, entity_id)
    _unlocked(row)
    production = await repos.productions.get(production_id)
    assert production is not None
    kind = CanonKind(row["kind"])
    card = body.card
    character = kind is CanonKind.CHARACTER
    current = row.get("current") or {}
    version = {
        "entity_id": str(entity_id), "production_id": str(production_id),
        "version": int(current.get("version") or 0) + 1, "card": card.model_dump(),
        "card_hash": hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True, ensure_ascii=False)
                                    .encode()).hexdigest(),
        "wardrobe_anchor": (body.wardrobe_anchor if body.wardrobe_anchor is not None
                            else wardrobe_anchor(card)) if character else "",
        "voice_pin": (body.voice_pin if body.voice_pin is not None else voice_pin(card)) if character else "",
        "reference_prompt": reference_sheet_prompt(kind, row["name"], card,
                                                   aspect_ratio=ASPECT_RATIO[Orientation(production["orientation"])]),
        "source": "user", "created_by": str(access.user.id),
    }
    created = await repos.canon.add_version(entity_id, version)
    await repos.audit.record(action="canon.version", entity="canon_entity", entity_id=str(entity_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"version": version["version"]})
    return CanonVersion.model_validate(created)


async def _set_lock(production_id: UUID, entity_id: UUID, access: ProductionAccess, repos: Repos,
                    locked: bool) -> CanonEntity:
    row = await _get(repos, production_id, entity_id)
    if bool(row.get("locked")) != locked:
        await repos.canon.update(entity_id, {
            "locked": locked, "locked_by": str(access.user.id) if locked else None,
            "locked_at": datetime.now(UTC).isoformat() if locked else None})
        await repos.audit.record(action="canon.lock" if locked else "canon.unlock", entity="canon_entity",
                                 entity_id=str(entity_id), actor_user_id=access.user.id,
                                 production_id=production_id)
    return _entity(await _get(repos, production_id, entity_id))


@router.post("/{entity_id}/lock", response_model=CanonEntity)
async def lock_canon(production_id: UUID, entity_id: UUID, access: CanEdit, repos: ReposDep) -> CanonEntity:
    return await _set_lock(production_id, entity_id, access, repos, True)


@router.post("/{entity_id}/unlock", response_model=CanonEntity)
async def unlock_canon(production_id: UUID, entity_id: UUID, access: CanEdit, repos: ReposDep) -> CanonEntity:
    return await _set_lock(production_id, entity_id, access, repos, False)
