"""Screen 1 (drama overview) and the 0b tree: episodes, their scenes, and shot counts.

Read-only here; scenes and shots are edited from the Director panel (Phase 3).
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
from contracts.canon import CanonKind
from contracts.production import EpisodeStatus, SceneStatus
from contracts.roles import Permission

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["structure"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]


class SceneSummary(BaseModel):
    id: UUID
    number: int
    heading: str
    title: str
    status: SceneStatus
    location_id: UUID | None
    shots: int
    runtime_s: int  # sum of its shots
    envelope_s: int


class EpisodeSummary(BaseModel):
    id: UUID
    number: int
    title: str
    synopsis: str
    status: EpisodeStatus
    scenes: int
    shots: int
    shots_ready: int  # shots with an accepted frame or a prompt
    shots_prompted: int = 0  # shots with a video prompt
    runtime_s: int
    openable: bool  # has scenes with shots: the Director panel can open it


class EpisodeDetail(EpisodeSummary):
    scene_list: list[SceneSummary]


class CanonCounts(BaseModel):
    characters: int
    core_characters: int
    locations: int
    props: int
    locked: int


class Structure(BaseModel):
    episodes: list[EpisodeDetail]
    canon: CanonCounts


def _scenes(scenes: list[Row], shots: list[Row]) -> dict[str, list[SceneSummary]]:
    by_scene: dict[str, list[Row]] = {}
    for s in shots:
        by_scene.setdefault(str(s["scene_id"]), []).append(s)
    out: dict[str, list[SceneSummary]] = {}
    for sc in sorted(scenes, key=lambda r: r["number"]):
        mine = by_scene.get(str(sc["id"]), [])
        out.setdefault(str(sc["episode_id"]), []).append(SceneSummary(
            id=sc["id"], number=sc["number"], heading=sc["heading"], title=sc["title"], status=sc["status"],
            location_id=sc.get("location_id"), shots=len(mine), runtime_s=sum(int(s["duration_s"]) for s in mine),
            envelope_s=sc["envelope_s"]))
    return out


def _episode(ep: Row, scenes: list[SceneSummary], shots: list[Row]) -> EpisodeDetail:
    ids = {str(s.id) for s in scenes}
    mine = [s for s in shots if str(s["scene_id"]) in ids]
    return EpisodeDetail(
        id=ep["id"], number=ep["number"], title=ep["title"], synopsis=ep["synopsis"], status=ep["status"],
        scenes=len(scenes), shots=len(mine), shots_ready=sum(1 for s in mine if s["status"] != "draft"),
        shots_prompted=sum(1 for s in mine if s["status"] == "prompt"),
        runtime_s=sum(int(s["duration_s"]) for s in mine), openable=any(s.shots for s in scenes),
        scene_list=scenes)


def episodes_of(episodes: list[Row], scenes: list[Row], shots: list[Row]) -> list[EpisodeDetail]:
    by_episode = _scenes(scenes, shots)
    return [_episode(ep, by_episode.get(str(ep["id"]), []), shots) for ep in episodes]


def structure_of(episodes: list[Row], scenes: list[Row], shots: list[Row], canon: list[Row]) -> Structure:
    """The structure from rows already read (the overview endpoint shares them with its canon list)."""
    chars = [c for c in canon if c["kind"] == CanonKind.CHARACTER]
    return Structure(episodes=episodes_of(episodes, scenes, shots), canon=CanonCounts(
        characters=len(chars), core_characters=sum(1 for c in chars if c.get("core")),
        locations=sum(1 for c in canon if c["kind"] == CanonKind.LOCATION),
        props=sum(1 for c in canon if c["kind"] == CanonKind.PROP),
        locked=sum(1 for c in canon if c.get("locked"))))


async def _structure(repos: Repos, production_id: UUID) -> list[EpisodeDetail]:
    shots, scenes, episodes = await asyncio.gather(
        repos.shots.list(production_id), repos.scenes.list(production_id), repos.episodes.list(production_id))
    return episodes_of(episodes, scenes, shots)


@router.get("/episodes", response_model=list[EpisodeSummary])
async def list_episodes(production_id: UUID, _: CanView, repos: ReposDep) -> list[EpisodeSummary]:
    return [EpisodeSummary.model_validate(e.model_dump(exclude={"scene_list"}))
            for e in await _structure(repos, production_id)]


@router.get("/episodes/{episode_id}", response_model=EpisodeDetail)
async def get_episode(production_id: UUID, episode_id: UUID, _: CanView, repos: ReposDep) -> EpisodeDetail:
    ep, shots, scene_rows = await asyncio.gather(
        repos.episodes.get(production_id, episode_id), repos.shots.list(production_id),
        repos.scenes.list(production_id, episode_id))
    if ep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found.")
    scenes = _scenes(scene_rows, shots).get(str(episode_id), [])
    return _episode(ep, scenes, shots)


@router.get("/structure", response_model=Structure)
async def get_structure(production_id: UUID, _: CanView, repos: ReposDep) -> Structure:
    """Everything the 0b tree and the screen 1 sidebar draw, in one read."""
    episodes, scenes, shots, canon = await asyncio.gather(
        repos.episodes.list(production_id), repos.scenes.list(production_id), repos.shots.list(production_id),
        repos.canon.list(production_id))
    return structure_of(episodes, scenes, shots, canon)
