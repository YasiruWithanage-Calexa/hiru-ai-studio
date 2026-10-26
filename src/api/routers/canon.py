"""The canon library (screen 1): characters, locations and props with versioned cards.

* A person's change to a card is a NEW VERSION (`source: user`), never an edit in place, so a
  shot written against version 3 can say so and be flagged when version 4 appears.
* LOCKED means approved: engines leave it alone, and people must unlock it before changing it.
* The voice pin and wardrobe anchor are derived from the card unless a person writes them.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import media_links, retrieval
from api.services.ai import AI, get_ai
from api.workers import task_manager
from contracts.canon import (
    CanonCard,
    CanonEntity,
    CanonEntityUpdate,
    CanonKind,
    CanonVersion,
    CanonVersionCreate,
    name_key,
    next_code,
    reference_sheet_prompt,
    voice_pin,
    wardrobe_anchor,
)
from contracts.documents import SearchRequest
from contracts.jobs import JobKind
from contracts.roles import Permission
from contracts.veo import ASPECT_RATIO, Orientation

router = APIRouter(prefix="/v1/productions/{production_id}/canon", tags=["canon"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanEdit = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]


class VersionView(CanonVersion):
    author: str = ""  # the person who made it, or "" for the extractor


class CanonDetail(CanonEntity):
    versions: list[VersionView]
    locked_by_name: str = ""
    locked_at: datetime | None = None


class SceneUse(BaseModel):
    scene_id: UUID
    label: str  # "Ep 01 · Scene 3"
    shots: int
    out_of_date: int  # shots designed against an older card of this entity


class Usage(BaseModel):
    shots: int
    out_of_date: int
    used_in: list[SceneUse] = Field(default_factory=list)


class CanonCreate(BaseModel):
    """A person's own entity: its identity and its first card (version 1, `source: user`)."""

    model_config = ConfigDict(extra="forbid")

    kind: CanonKind
    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    core: bool = False
    card: CanonCard = Field(default_factory=CanonCard)
    wardrobe_anchor: str | None = Field(default=None, max_length=600)
    voice_pin: str | None = Field(default=None, max_length=400)
    lock: bool = False  # "Save and lock"


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CanonKind
    name: str = Field(min_length=1, max_length=120)


class Draft(BaseModel):
    """What the documents say about a name: sentences that mention it, with where they are."""

    look: str
    sources: list[str]


async def usage_by_entity(repos: Repos, production_id: UUID) -> dict[str, Usage]:
    """Which shots each entity is in (its lines, its scenes, the people a design pinned), and how
    many were designed against an older card. Read on demand; nothing is stored."""
    canon_rows, scene_rows, episode_rows, line_rows, shot_rows = await asyncio.gather(
        repos.canon.list(production_id), repos.scenes.list(production_id), repos.episodes.list(production_id),
        repos.lines.list_for_production(production_id), repos.shots.list(production_id))
    canon = {str(c["id"]): c for c in canon_rows}
    current = {k: int((c.get("current") or {}).get("version") or 0) for k, c in canon.items()}
    scenes = {str(s["id"]): s for s in scene_rows}
    episodes = {str(e["id"]): int(e["number"]) for e in episode_rows}
    speakers: dict[str, set[str]] = {}
    for ln in line_rows:
        if ln.get("shot_id") and ln.get("character_id"):
            speakers.setdefault(str(ln["shot_id"]), set()).add(str(ln["character_id"]))
    per: dict[str, dict[str, list[int]]] = {}
    for shot in shot_rows:
        scene = scenes.get(str(shot["scene_id"])) or {}
        pinned = ((shot.get("design") or {}).get("pins") or {}).get("canon") or {}
        members = set(speakers.get(str(shot["id"]), set())) | set(pinned)
        if scene.get("location_id"):
            members.add(str(scene["location_id"]))
        for entity_id in members & set(canon):
            old = entity_id in pinned and int(pinned[entity_id]) != current[entity_id]
            row = per.setdefault(entity_id, {}).setdefault(str(shot["scene_id"]), [0, 0])
            row[0] += 1
            row[1] += int(old)
    out: dict[str, Usage] = {}
    for entity_id, by_scene in per.items():
        uses = []
        for scene_id, (shots, stale) in by_scene.items():
            scene = scenes.get(scene_id) or {}
            ep = episodes.get(str(scene.get("episode_id")), 0)
            uses.append(SceneUse(scene_id=UUID(scene_id), label=f"Ep {ep:02d} · Scene {scene.get('number', 0)}",
                                 shots=shots, out_of_date=stale))
        uses.sort(key=lambda u: u.label)
        out[entity_id] = Usage(shots=sum(u.shots for u in uses), out_of_date=sum(u.out_of_date for u in uses),
                               used_in=uses)
    return out


def _version_row(entity: Row, card: CanonCard, production: Row, user_id: UUID, number: int,
                 wardrobe: str | None, voice: str | None) -> Row:
    kind = CanonKind(entity["kind"])
    character = kind is CanonKind.CHARACTER
    return {
        "entity_id": str(entity["id"]), "production_id": str(entity["production_id"]), "version": number,
        "card": card.model_dump(),
        "card_hash": hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True, ensure_ascii=False)
                                    .encode()).hexdigest(),
        "wardrobe_anchor": (wardrobe if wardrobe is not None else wardrobe_anchor(card)) if character else "",
        "voice_pin": (voice if voice is not None else voice_pin(card)) if character else "",
        "reference_prompt": reference_sheet_prompt(kind, entity["name"], card,
                                                   aspect_ratio=ASPECT_RATIO[Orientation(production["orientation"])]),
        "source": "user", "created_by": str(user_id),
    }


def _sheet_url(current: Row | None) -> str:
    assets = (current or {}).get("reference_assets") or []
    first = assets[0] if assets else None
    path = first.get("path") if isinstance(first, dict) else first
    return media_links.url("references", str(path)) if path else ""


def _entity(row: Row) -> CanonEntity:
    current = row.get("current")
    return CanonEntity.model_validate({**row, "current": current,
                                       "current_version": current["version"] if current else None,
                                       "reference_sheet_url": _sheet_url(current)})


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


@router.get("/usage", response_model=dict[str, Usage])
async def canon_usage(production_id: UUID, _: CanView, repos: ReposDep) -> dict[str, Usage]:
    """Shot counts per entity for the library (entity id → usage, without the per-scene rows)."""
    return {k: Usage(shots=u.shots, out_of_date=u.out_of_date)
            for k, u in (await usage_by_entity(repos, production_id)).items()}


@router.post("", response_model=CanonEntity, status_code=status.HTTP_201_CREATED)
async def create_canon(production_id: UUID, body: CanonCreate, access: CanEdit, repos: ReposDep) -> CanonEntity:
    existing = await repos.canon.list(production_id)
    name = " ".join(body.name.split())
    clash = next((r for r in existing if r["kind"] == body.kind and name_key(r["name"]) == name_key(name)), None)
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{clash['code']} already has this name.")
    production = access.production
    entity = await repos.canon.create({
        "production_id": str(production_id), "kind": body.kind.value, "name": name,
        "code": next_code(body.kind, {str(r["code"]) for r in existing}),
        "aliases": [a.strip() for a in body.aliases if a.strip()], "core": body.core})
    await repos.canon.add_version(UUID(str(entity["id"])), _version_row(
        entity, body.card, production, access.user.id, 1, body.wardrobe_anchor, body.voice_pin))
    if body.lock:
        await repos.canon.update(UUID(str(entity["id"])), {
            "locked": True, "locked_by": str(access.user.id), "locked_at": datetime.now(UTC).isoformat()})
    await repos.audit.record(action="canon.create", entity="canon_entity", entity_id=str(entity["id"]),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"code": entity["code"], "name": name, "locked": body.lock})
    return _entity(await _get(repos, production_id, UUID(str(entity["id"]))))


@router.post("/draft", response_model=Draft)
async def draft_canon(production_id: UUID, body: DraftRequest, access: CanEdit, repos: ReposDep,
                      ai: Annotated[AI, Depends(get_ai)]) -> Draft:
    """What the production's documents say about a name, to start a card from. Sentences are
    quoted, never invented; the person writes the card."""
    found = await retrieval.search(repos, ai, production_id=production_id, actor_user_id=access.user.id,
                                   req=SearchRequest(query=body.name, k=6, rerank=False))
    key = name_key(body.name)
    sentences: list[str] = []
    sources: list[str] = []
    for hit in found.hits:
        mentions = [s.strip() for s in re.split(r"(?<=[.!?])\s+", hit.content)
                    if key and key in name_key(s) and len(s.strip()) > 3]
        if not mentions:
            continue
        sentences += [m for m in mentions if m not in sentences][:2]
        page = f" · p. {hit.citation.page_start}" if hit.citation.page_start else ""
        sources.append(f"{hit.citation.filename or hit.heading}{page}")
        if len(sentences) >= 4:
            break
    return Draft(look=" ".join(sentences[:4]), sources=list(dict.fromkeys(sources)))


@router.get("/{entity_id}", response_model=CanonDetail)
async def get_canon(production_id: UUID, entity_id: UUID, _: CanView, repos: ReposDep) -> CanonDetail:
    row = await _get(repos, production_id, entity_id)
    names = {str(p["id"]): str(p.get("display_name") or "") for p in await repos.profiles.list()}
    versions = [VersionView.model_validate({**v, "author": names.get(str(v.get("created_by")), "")})
                for v in await repos.canon.versions(entity_id)]
    return CanonDetail(**_entity(row).model_dump(), versions=versions,
                       locked_by_name=names.get(str(row.get("locked_by")), "") if row.get("locked") else "",
                       locked_at=row.get("locked_at") if row.get("locked") else None)


@router.get("/{entity_id}/usage", response_model=Usage)
async def entity_usage(production_id: UUID, entity_id: UUID, _: CanView, repos: ReposDep) -> Usage:
    await _get(repos, production_id, entity_id)
    return (await usage_by_entity(repos, production_id)).get(str(entity_id), Usage(shots=0, out_of_date=0))


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
    production = access.production
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


class SheetStarted(BaseModel):
    job_id: UUID


@router.post("/{entity_id}/reference-sheet", response_model=SheetStarted, status_code=status.HTTP_202_ACCEPTED)
async def make_reference_sheet(production_id: UUID, entity_id: UUID, access: CanEdit,
                               repos: ReposDep) -> SheetStarted:
    """Paint a reference sheet for the CURRENT card (`frame_render`). Frames of shots with this
    character or place attach it, so faces and places hold across shots. A new card version
    needs its own sheet; frames made from an older one are reported out of date anyway."""
    row = await _get(repos, production_id, entity_id)
    if not row.get("current"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has no card yet.")
    job_id = await task_manager.dispatch(JobKind.FRAME_RENDER, repos, actor_user_id=access.user.id,
                                         production_id=production_id, request={"entity_id": str(entity_id)},
                                         state={"reference_entity_id": str(entity_id)})
    await repos.audit.record(action="canon.reference_sheet", entity="canon_entity", entity_id=str(entity_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"job_id": str(job_id)})
    return SheetStarted(job_id=job_id)
