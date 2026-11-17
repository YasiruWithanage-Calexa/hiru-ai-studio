"""The Scene board (plan/2026-11-14 §3.3, §3.6): one mannequin storyboard per scene, painted before any first frame.

    GET    .../scenes/{id}/board                    the scene's current board: parts, cells, conflicts, out of date
    POST   .../scenes/{id}/board                    paint the whole board (job): a new version; notes and locked
                                                    panels of the current one carry over
    POST   .../scene-boards/{id}/approve            approve one part (only an approved, current board feeds frames, D3)
    PATCH  .../scene-boards/{id}/cells/{shot_id}    a panel's note or lock
    POST   .../scenes/{id}/board/update             Update board (job, plan/2026-11-17): each changed or added shot's
                                                    panel painted ALONE, removed and moved shots tidied, every other
                                                    panel untouched; the named shots, else everything out of date;
                                                    locked panels never

A board is never repainted by itself when a shot changes (the person, 2026-11-13): the view says what is out of date
and a person presses Update board. The masked repaint is gone (plan/2026-11-17 D3: the image model does not honour a
mask).
The scene LOCK (approval) closes this picture work, as it closes frames. Pictures are streamed through
`/files/{ticket}`; no storage URL reaches a browser. No costs are shown anywhere (CLAUDE.md).
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import boards, media_links
from api.services.production import LOCKED
from api.workers import task_manager
from contracts import board as kit
from contracts.jobs import JobKind
from contracts.production import SceneStatus
from contracts.roles import Permission
from contracts.veo import ASPECT_RATIO, Orientation

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["scene-board"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanGenerate = Annotated[ProductionAccess, Depends(require_permission(Permission.GENERATE))]
NO_TABLE = "The Scene board needs database schema v26 (Database/upgrade_v25_to_v26.sql)."


# ── views ──────────────────────────────────────────────────────────────────────────────────


class BoardCellView(BaseModel):
    shot_id: UUID
    number: int
    kind: str  # painted | black
    panel: int | None  # its place in the painted picture (1-based); None for a black plate
    url: str | None  # /files/{ticket}, never a storage URL
    thumb_url: str | None
    file_key: str | None
    text: str  # a black plate's script line
    note: str
    locked: bool
    stale: bool  # the shot changed since this panel was painted
    fresh: bool = False  # painted (or put back) by the latest Update board: look at it, approve it again


class BoardPartView(BaseModel):
    id: UUID
    version: int
    part: int
    parts: int
    status: str  # queued | running | done | failed | refused
    quality: str  # low | medium (D2: never high)
    error: str | None
    approved: bool
    sheet_url: str | None
    sheet_thumb_url: str | None
    sheet_key: str | None
    cells: list[BoardCellView]
    created_at: str


class BoardUpdateItem(BaseModel):
    number: int  # the shot's number now (a removed shot's, its number on the board)
    what: Literal["changed", "added", "removed", "moved", "locked"]


class SceneBoardView(BaseModel):
    scene_id: UUID
    # none | painting | failed | ready (painted, waiting for approval) | approved | stale
    state: str
    parts: list[BoardPartView]
    conflicts: list[str]  # what the board writer found disagreeing in the data: advice, not a block
    stale_reasons: list[str]  # "shots 4 and 7 changed", "shot 9 added", ...
    changed: list[int]  # shot numbers whose panels changed (a locked one included)
    # plan/2026-11-17: what Update board does, shot by shot (`changed | added | removed | moved | locked`); a locked
    # shot is left as it is ("unlock to update")
    update: list[BoardUpdateItem] = Field(default_factory=list)
    # only a whole repaint mends it: no finished board, a part that failed, or the board is in the wrong shape
    whole: bool
    approved: bool  # every part approved
    job_id: UUID | None  # the job painting it now, if any
    # The board's shape: "16:9" (wide panels) or "9:16" (tall), the production's when there is no board yet. A board
    # painted before the production's shape changed (or before tall boards, 2026-11-16) keeps its old shape:
    # `wrong_shape` says so (advice: its panels still work, a whole repaint gives the production's shape).
    aspect: str = "16:9"
    wrong_shape: bool = False


class BoardStarted(BaseModel):
    job_id: UUID
    board_id: UUID


class PaintRequest(BaseModel):
    quality: Literal["low", "medium"] = "low"  # D2: LOW by default, MEDIUM a setting, never HIGH


class UpdateRequest(BaseModel):
    shots: list[UUID] = Field(default_factory=list)  # shot ids; empty = every shot out of date


class CellUpdate(BaseModel):
    note: str | None = Field(default=None, max_length=300)
    locked: bool | None = None


def _cell_view(cell: Row, stale_numbers: set[int]) -> BoardCellView:
    path = str(cell.get("path") or "")
    return BoardCellView(
        shot_id=cell["shot_id"], number=int(cell.get("number") or 0), kind=str(cell.get("kind") or "painted"),
        panel=cell.get("panel"), url=media_links.url("frames", path) or None,
        thumb_url=media_links.thumb_url("frames", path) or None,
        file_key=media_links.key("frames", path) if path else None, text=str(cell.get("text") or ""),
        note=str(cell.get("note") or ""), locked=bool(cell.get("locked")),
        stale=int(cell.get("number") or 0) in stale_numbers and cell.get("kind") == "painted",
        fresh=bool(cell.get("fresh")))


def _part_view(row: Row, stale_numbers: set[int]) -> BoardPartView:
    sheet = str(row.get("sheet_path") or "")
    return BoardPartView(
        id=row["id"], version=int(row.get("version") or 1), part=int(row.get("part") or 1),
        parts=int(row.get("parts") or 1), status=str(row.get("status") or "queued"),
        quality=str(row.get("quality") or "low"), error=row.get("error"), approved=bool(row.get("approved_at")),
        sheet_url=media_links.url("frames", sheet) or None, sheet_thumb_url=media_links.thumb_url("frames", sheet)
        or None, sheet_key=media_links.key("frames", sheet) if sheet else None,
        cells=[_cell_view(c, stale_numbers) for c in row.get("cells") or []], created_at=str(row.get("created_at")))


def board_view(scene_id: UUID, rows: list[Row], shots: list[Row], production_aspect: str = "16:9") -> SceneBoardView:
    parts = boards.current(rows)
    wanted = kit.board_aspect(production_aspect)
    painted = [p for p in parts if p.get("prompt")]
    aspect = kit.aspect_of_board(painted[0]) if painted else wanted
    st = boards.stale(parts, shots)
    stale_numbers = set(st.changed)
    painting = [p for p in parts if p.get("status") in ("queued", "running")]
    wrong_shape = bool(painted) and aspect != wanted
    whole = bool(parts) and not painting and (not boards.updatable(parts) or wrong_shape)
    if not parts:
        state = "none"
    elif painting:
        state = "painting"
    elif all(p.get("status") in ("failed", "refused") for p in parts):
        state = "failed"
    elif st.any:
        state = "stale"
    elif all(p.get("approved_at") for p in parts):
        state = "approved"
    else:
        state = "ready"
    conflicts: list[str] = []
    for p in parts:
        conflicts += [c for c in (p.get("writer") or {}).get("conflicts") or [] if c not in conflicts]
    job = next((p.get("job_id") for p in painting if p.get("job_id")), None)
    return SceneBoardView(scene_id=scene_id, state=state, parts=[_part_view(p, stale_numbers) for p in parts],
                          conflicts=conflicts, stale_reasons=st.reasons(), changed=sorted(st.changed),
                          update=[BoardUpdateItem(number=n, what=w) for n, w in st.items()],  # type: ignore[arg-type]
                          whole=whole, approved=bool(parts) and all(p.get("approved_at") for p in parts),
                          job_id=job, aspect=aspect, wrong_shape=wrong_shape)


# ── helpers ────────────────────────────────────────────────────────────────────────────────


async def _scene(repos: Repos, access: ProductionAccess, scene_id: UUID) -> tuple[Row, list[Row], list[Row]]:
    scene, shots, rows = await asyncio.gather(repos.scenes.get(access.production_id, scene_id),
                                              repos.shots.list(access.production_id, scene_id),
                                              repos.scene_boards.list(scene_id))
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    return scene, shots, rows


async def _board(repos: Repos, access: ProductionAccess, board_id: UUID) -> Row:
    row = await repos.scene_boards.get(access.production_id, board_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board not found.")
    return row


def _unlocked(scene: Row) -> None:
    if scene.get("status") == SceneStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED)


def _current_only(row: Row, rows: list[Row]) -> None:
    if str(row["id"]) not in {str(p["id"]) for p in boards.current(rows)}:
        raise HTTPException(status.HTTP_409_CONFLICT, "This is an older board. Reload the scene.")


async def _audit(repos: Repos, access: ProductionAccess, action: str, entity_id: str, diff: Row) -> None:
    await repos.audit.record(action=action, entity="scene_board", entity_id=entity_id, actor_user_id=access.user.id,
                             production_id=access.production_id, diff=diff)


async def _view(repos: Repos, access: ProductionAccess, scene_id: UUID) -> SceneBoardView:
    _, shots, rows = await _scene(repos, access, scene_id)
    orientation = Orientation(access.production.get("orientation") or "horizontal")
    return board_view(scene_id, rows, shots, ASPECT_RATIO[orientation])


# ── routes ─────────────────────────────────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/board", response_model=SceneBoardView)
async def get_board(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> SceneBoardView:
    return await _view(repos, access, scene_id)


@router.post("/scenes/{scene_id}/board", response_model=BoardStarted, status_code=status.HTTP_202_ACCEPTED)
async def paint_board(production_id: UUID, scene_id: UUID, body: PaintRequest, access: CanGenerate,
                      repos: ReposDep) -> BoardStarted:
    """A whole board for the scene, as a new version. The job makes the missing face sheets first (D4), writes the
    board, paints it at `quality` and cuts it into panels; a scene of more than 16 painted shots becomes parts (D5)."""
    scene, shots, rows = await _scene(repos, access, scene_id)
    _unlocked(scene)
    if not shots:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no shots yet. Plan the scene first.")
    parts = boards.current(rows)
    if any(p.get("status") in ("queued", "running") for p in parts):
        raise HTTPException(status.HTTP_409_CONFLICT, "The scene board is already being painted.")
    board_id = str(uuid4())
    row = {"id": board_id, "production_id": str(access.production_id), "scene_id": str(scene_id),
           "version": boards.next_version(rows), "part": 1, "parts": 1, "status": "queued", "quality": body.quality,
           "created_by": str(access.user.id)}
    try:
        await repos.scene_boards.create(row)
    except Exception:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_TABLE) from None
    state: Row = {"board_id": board_id, "carry": [str(p["id"]) for p in parts if p.get("status") == "done"]}
    try:
        job_id = await task_manager.dispatch(JobKind.FRAME_RENDER, repos, actor_user_id=access.user.id,
                                             production_id=access.production_id,
                                             request={"scene_id": str(scene_id), "board": body.quality}, state=state)
    except RuntimeError:
        await repos.scene_boards.update(UUID(board_id), {"status": "failed", "error": "The job could not be started."})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The board could not be started. Try again.") from None
    await repos.scene_boards.update(UUID(board_id), {"job_id": str(job_id)})
    await _audit(repos, access, "board.request", board_id, {"job_id": str(job_id), "quality": body.quality,
                                                            "version": row["version"]})
    return BoardStarted(job_id=job_id, board_id=UUID(board_id))


@router.post("/scene-boards/{board_id}/approve", response_model=SceneBoardView)
async def approve_board(production_id: UUID, board_id: UUID, access: CanGenerate, repos: ReposDep) -> SceneBoardView:
    row = await _board(repos, access, board_id)
    scene, _, rows = await _scene(repos, access, UUID(str(row["scene_id"])))
    _unlocked(scene)
    _current_only(row, rows)
    if row.get("status") != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a finished board can be approved.")
    if not await repos.scene_boards.approve(UUID(str(row["scene_id"])), int(row.get("part") or 1), board_id,
                                            access.user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone changed the board meanwhile. Reload the scene.")
    await _audit(repos, access, "board.approve", str(board_id), {"part": int(row.get("part") or 1)})
    return await _view(repos, access, UUID(str(row["scene_id"])))


@router.patch("/scene-boards/{board_id}/cells/{shot_id}", response_model=SceneBoardView)
async def update_cell(production_id: UUID, board_id: UUID, shot_id: UUID, body: CellUpdate, access: CanGenerate,
                      repos: ReposDep) -> SceneBoardView:
    """A panel's note (sent to the writer when that panel is repainted, never for others) or its lock (a locked panel
    is never repainted). Neither changes the picture or the approval."""
    row = await _board(repos, access, board_id)
    scene, _, rows = await _scene(repos, access, UUID(str(row["scene_id"])))
    _unlocked(scene)
    _current_only(row, rows)
    cells = [dict(c) for c in row.get("cells") or []]
    cell = next((c for c in cells if str(c.get("shot_id")) == str(shot_id) and c.get("kind") == "painted"), None)
    if cell is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This shot has no panel on this board.")
    if body.note is not None:
        cell["note"] = " ".join(body.note.split())
    if body.locked is not None:
        cell["locked"] = body.locked
    await repos.scene_boards.update(board_id, {"cells": cells})
    await _audit(repos, access, "board.cell", str(board_id), {"shot_id": str(shot_id),
                                                              **body.model_dump(exclude_none=True)})
    return await _view(repos, access, UUID(str(row["scene_id"])))


async def _planning(repos: Repos, production_id: UUID) -> bool:
    """A plan or a build of this production runs: the shots may change under the update."""
    busy = {k.value for k in (*task_manager.PLANNING, JobKind.STRUCTURE_BUILD)}
    return any(str(r.get("kind")) in busy for r in await repos.jobs.live(production_id, None)
               if r.get("status") in ("pending", "running"))


@router.post("/scenes/{scene_id}/board/update", response_model=BoardStarted, status_code=status.HTTP_202_ACCEPTED)
async def update_board(production_id: UUID, scene_id: UUID, body: UpdateRequest, access: CanGenerate,
                       repos: ReposDep) -> BoardStarted:
    """Update board (plan/2026-11-17 §3.1): one job for the scene's current board. Each changed or added shot's panel
    is painted ALONE with its neighbours attached; a removed shot's cell is dropped and moved shots put in order;
    every other panel stays exactly as it is; a locked panel is never repainted. Every part is set `queued` with its
    approval cleared (the schema allows an approval only on a done part); the job writes the person's approval back
    to a part none of whose cells changed (§3.3)."""
    scene, shots, rows = await _scene(repos, access, scene_id)
    _unlocked(scene)
    parts = boards.current(rows)
    if any(p.get("status") in ("queued", "running") for p in parts):
        raise HTTPException(status.HTTP_409_CONFLICT, "The scene board is already being painted.")
    if not parts or not boards.updatable(parts):
        raise HTTPException(status.HTTP_409_CONFLICT, boards.PAINT_FIRST)
    orientation = Orientation(access.production.get("orientation") or "horizontal")
    if kit.aspect_of_board(parts[0]) != kit.board_aspect(ASPECT_RATIO[orientation]):
        raise HTTPException(status.HTTP_409_CONFLICT, boards.WRONG_SHAPE)
    st = boards.stale(parts, shots)
    wanted = [str(s) for s in body.shots]
    if wanted:
        known = {str(s["id"]) for s in shots}
        if [s for s in wanted if s not in known]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Shot not found in this scene.")
        if [s for s in wanted if s not in st.paint]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a shot that changed or was added can be updated "
                                                          "(a locked panel: unlock it first).")
    if not (st.paint or st.tidy):
        locked = f" {kit.shots_phrase(st.locked)} changed but is locked: unlock it to update it." if st.locked else ""
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing on the board is out of date." + locked)
    if await _planning(repos, access.production_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "The scene is being planned. Update the board when it is done.")
    ids = [str(p["id"]) for p in parts]
    approvals = {str(p["id"]): {"approved_at": p.get("approved_at"), "approved_by": p.get("approved_by")}
                 for p in parts if p.get("approved_at")}
    for p in parts:
        await repos.scene_boards.update(UUID(str(p["id"])), {"status": "queued", "approved_at": None,
                                                             "approved_by": None, "error": None})
    state: Row = {"update": True, "scene_id": str(scene_id), "board_ids": ids, "shots": wanted,
                  "approvals": approvals}
    try:
        job_id = await task_manager.dispatch(JobKind.FRAME_RENDER, repos, actor_user_id=access.user.id,
                                             production_id=access.production_id,
                                             request={"scene_id": str(scene_id), "board_update": wanted}, state=state)
    except RuntimeError:
        for p in parts:  # nothing started: the board is back as it was, with its approval
            await repos.scene_boards.update(UUID(str(p["id"])), {"status": "done", **approvals.get(str(p["id"]), {}),
                                                                 "error": "The update could not be started."})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The update could not be started. Try again.") \
            from None
    for p in parts:
        await repos.scene_boards.update(UUID(str(p["id"])), {"job_id": str(job_id)})
    await _audit(repos, access, "board.update", ids[0], {"job_id": str(job_id), "shots": wanted,
                                                         "paint": len([s for s in st.paint
                                                                       if not wanted or s in wanted]),
                                                         "tidy": len(st.tidy)})
    return BoardStarted(job_id=job_id, board_id=UUID(ids[0]))
