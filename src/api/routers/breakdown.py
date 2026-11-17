"""The scene packet, read-only, and the one-scene refresh (plan/2026-11-11 §7, phases 5 and 6).

    GET  /v1/productions/{pid}/scenes/{sid}/packet               the scene's packet as every planner reads it (VIEW)
    POST /v1/productions/{pid}/scenes/{sid}/breakdown/refresh    break the scene down again after a person's edit
                                                                 (EDIT_SCRIPT): a structure_build job on that scene

The packet says what happens and what is true in the scene; it holds no shot sizes, no model, no tier and no cost. A
packet made for an earlier script version is `stale` until the refresh. A production the caller cannot see is 404, as
everywhere; a scene with no packet (no breakdown yet, or a database before schema v21) is 404 with a sentence.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos
from api.workers import task_manager
from contracts.jobs import JobKind
from contracts.roles import Permission

router = APIRouter(tags=["breakdown"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanWrite = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_SCRIPT))]
NO_PACKET = "This scene has no breakdown yet."


class PacketView(BaseModel):
    scene_key: str  # the breakdown's id for the scene: E01-S03
    packet: dict[str, Any]  # contracts.breakdown.packet.assemble; {} when the scene has no breakdown yet
    waits: list[str]  # why planning from it waits; [] = complete
    stale: bool  # the script changed after the breakdown was made: refresh it
    ready: bool  # complete and current: a planner may read it


class RefreshStarted(BaseModel):
    job_id: UUID


async def _scene_and_packet(repos: Repos, production_id: UUID, scene_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
    scene = await repos.scenes.get(production_id, scene_id)
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    row = await repos.packets.get(production_id, scene_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_PACKET)
    return scene, row


@router.get("/v1/productions/{production_id}/scenes/{scene_id}/packet", response_model=PacketView)
async def get_packet(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> PacketView:
    scene, row = await _scene_and_packet(repos, access.production_id, scene_id)
    return packet_view(scene, row)


def packet_view(scene: dict[str, Any], row: dict[str, Any]) -> PacketView:
    """A scene's packet as the page shows it (also in `/page`, plan/2026-11-13d phase 4)."""
    stale = int(row.get("script_version") or 0) != int(scene.get("script_version") or 1)
    waits = [str(w) for w in row.get("waits") or []]
    return PacketView(
        scene_key=str(row["scene_key"]),
        packet=dict(row.get("packet") or {}),
        waits=waits,
        stale=stale,
        ready=not waits and not stale,
    )


@router.post(
    "/v1/productions/{production_id}/scenes/{scene_id}/breakdown/refresh",
    response_model=RefreshStarted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_breakdown(production_id: UUID, scene_id: UUID, access: CanWrite, repos: ReposDep) -> RefreshStarted:
    await _scene_and_packet(repos, access.production_id, scene_id)
    job_id = await task_manager.dispatch(
        JobKind.STRUCTURE_BUILD,
        repos,
        actor_user_id=access.user.id,
        production_id=access.production_id,
        request={"scene_id": str(scene_id)},
        state={"breakdown_refresh": str(scene_id)},
    )
    await repos.audit.record(
        action="scene.breakdown_refresh",
        entity="scene",
        entity_id=str(scene_id),
        actor_user_id=access.user.id,
        production_id=access.production_id,
        diff={"job_id": str(job_id)},
    )
    return RefreshStarted(job_id=job_id)
