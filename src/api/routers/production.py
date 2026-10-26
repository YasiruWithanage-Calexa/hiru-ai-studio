"""Screen 3d, the Production panel: a scene's shots with their camera, first frames and video
prompt (PLAN.md §10, §13 Phase 4). Rules in `api/services/production.py`.

    GET   .../scenes/{id}/production      every shot of the scene, as the panel draws it
    GET   .../shots/{id}                  one shot
    POST  .../scenes/{id}/design          camera recommendations for the scene (job)
    PATCH .../shots/{id}/camera           a person's camera (null = back to the recommendation)
    POST  .../shots/{id}/frames           first frames for one shot (job)
    POST  .../scenes/{id}/frames          first frames for every shot that needs one (job)
    POST  .../shots/{id}/frames/upload    a frame a person made elsewhere
    POST  .../frames/{id}/accept|reject   picking is free; accepting unlocks the prompt
    POST  .../shots/{id}/prompt           a new prompt version (job), once unlocked
    POST  .../scenes/{id}/prompts         prompts for every unlocked shot of the scene (job)
    GET   .../shots/{id}/prompt|prompts   the latest prompt / every version

Frames are streamed through `/files/{ticket}`; no storage URL reaches a browser. No costs are
shown anywhere (CLAUDE.md).
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import media_links
from api.services.production import NOT_APPROVED, ShotState, camera_checks, scene_states
from api.workers import task_manager
from contracts.jobs import JobKind
from contracts.producer import (
    CameraField,
    CameraSettings,
    CameraUpdate,
    Check,
    PromptSection,
    frame_prompt,
    storyboard_note,
)
from contracts.production import Framing, SceneStatus, ShotStatus
from contracts.roles import Permission
from contracts.veo import ASPECT_RATIO, CameraLink, FrameStrategy, Orientation, SoundMode

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["production"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanGenerate = Annotated[ProductionAccess, Depends(require_permission(Permission.GENERATE))]
MAX_FRAMES_PER_REQUEST = 4


# ── views ──────────────────────────────────────────────────────────────────────────────────


class DesignView(BaseModel):
    state: str  # missing | current | stale
    stale_reasons: list[str]
    planner: str  # model | rules
    rationale: str
    designed_at: str | None


class CameraView(BaseModel):
    recommended: CameraSettings
    current: CameraSettings
    changed: list[CameraField]  # fields a person changed
    storyboard_note: str  # "50mm · dolly in"


class FrameView(BaseModel):
    id: UUID
    label: str  # "First frame 2"
    status: str  # queued | running | done | failed | refused
    url: str | None  # /files/{ticket}, never a storage URL
    error: str | None
    rejected_reason: str | None
    accepted: bool
    stale: bool
    stale_reasons: list[str]
    created_at: str


class PromptView(BaseModel):
    id: UUID
    version: int
    model: str
    sections: list[PromptSection]
    prose: str
    checks: list[Check]
    frame_id: UUID | None
    created_at: str
    stale: bool
    stale_reasons: list[str]


class LockView(BaseModel):
    locked: bool
    reason: str


class ShotLine(BaseModel):
    """A spoken line, verbatim (Sinhala: render with `lang="si"`)."""

    id: UUID
    speaker: str
    character_id: UUID | None
    text: str
    delivery: str
    words: int
    start_s: float | None


class ShotProductionView(BaseModel):
    id: UUID
    scene_id: UUID
    code: str
    number: int
    title: str
    framing: Framing
    duration_s: int
    start_s: int
    sound_mode: SoundMode
    camera_link: CameraLink
    frame_strategy: FrameStrategy
    status: ShotStatus
    version: int
    lines: list[ShotLine]
    canon_refs: list[str]  # "C01 v2", "L01 v1": the cards this shot is pinned to now
    design: DesignView
    camera: CameraView
    checks: list[Check]
    frame_prompt: str  # what the next frame will be asked for ("" until designed)
    frames: list[FrameView]
    accepted_frame_id: UUID | None
    prompt_lock: LockView
    prompt: PromptView | None


class SceneProductionView(BaseModel):
    id: UUID
    production_id: UUID
    episode_id: UUID
    number: int
    heading: str
    title: str
    status: SceneStatus
    approved: bool
    aspect_ratio: str
    shots: list[ShotProductionView]


class Started(BaseModel):
    job_id: UUID
    frame_ids: list[UUID] = Field(default_factory=list)


class DesignRequest(BaseModel):
    force: bool = False  # re-design shots whose design is still current


class FramesRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=MAX_FRAMES_PER_REQUEST)


class SceneFramesRequest(FramesRequest):
    only_missing: bool = True  # skip shots that already have an accepted, current frame


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


# ── loading ────────────────────────────────────────────────────────────────────────────────


class Loaded:
    def __init__(self, production: Row, scene: Row, states: list[ShotState], lines: list[Row]) -> None:
        self.production, self.scene, self.states, self.lines = production, scene, states, lines

    @property
    def aspect(self) -> str:
        return ASPECT_RATIO[Orientation(self.production.get("orientation") or "horizontal")]

    @property
    def approved(self) -> bool:
        return self.scene.get("status") == SceneStatus.APPROVED

    def state(self, shot_id: UUID | str) -> ShotState:
        return next(s for s in self.states if s.id == str(shot_id))


async def load(repos: Repos, access: ProductionAccess, scene_id: UUID) -> Loaded:
    production_id = access.production_id
    scene, shots, lines, canon = await asyncio.gather(
        repos.scenes.get(production_id, scene_id), repos.shots.list(production_id, scene_id),
        repos.lines.list(scene_id), repos.canon.list(production_id))
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    ids = [str(s["id"]) for s in shots]
    frames, prompts = await asyncio.gather(repos.frames.list_for_shots(ids), repos.prompts.latest_for_shots(ids))
    states = scene_states(scene, shots, lines, canon, frames, prompts)
    return Loaded(access.production, scene, states, lines)


async def load_shot(repos: Repos, access: ProductionAccess, shot_id: UUID) -> tuple[Loaded, ShotState]:
    shot = await repos.shots.get(access.production_id, shot_id)
    if shot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shot not found.")
    ld = await load(repos, access, UUID(str(shot["scene_id"])))
    return ld, ld.state(shot_id)


def _prompt_view(row: Row, reasons: list[str]) -> PromptView:
    return PromptView(id=row["id"], version=int(row["version"]), model=str(row.get("model") or ""),
                      sections=[PromptSection.model_validate(s) for s in row.get("sections") or []],
                      prose=str(row.get("prose") or ""),
                      checks=[Check.model_validate(c) for c in row.get("checks") or []],
                      frame_id=row.get("frame_id"), created_at=str(row["created_at"]), stale=bool(reasons),
                      stale_reasons=reasons)


def shot_view(ld: Loaded, st: ShotState, checks: list[Check]) -> ShotProductionView:
    row, design = st.row, st.row.get("design") or {}
    by_line = {str(ln["id"]): ln for ln in ld.lines}
    lines = []
    for item in st.items:
        ln = by_line.get(item.line_id or "") if item.is_line else None
        if ln:
            lines.append(ShotLine(id=ln["id"], speaker=ln["speaker"], character_id=ln.get("character_id"),
                                  text=ln["text"], delivery=ln.get("delivery") or "", words=int(ln.get("words") or 0),
                                  start_s=ln.get("start_s")))
    frames = []
    for n, f in enumerate(st.frames, start=1):
        reasons = st.frame_reasons.get(str(f["id"]), [])
        frames.append(FrameView(
            id=f["id"], label=f"First frame {n}", status=str(f["status"]),
            url=media_links.url("frames", str(f["storage_path"])) if f.get("storage_path") else None,
            error=f.get("error"), rejected_reason=f.get("rejected_reason"), accepted=bool(f.get("accepted_at")),
            stale=bool(reasons), stale_reasons=reasons, created_at=str(f["created_at"])))
    state = "missing" if st.design_reasons == ["no design"] else ("stale" if st.design_reasons else "current")
    changed = [CameraField(k) for k, v in st.camera.model_dump().items() if v != getattr(st.recommended, k)]
    return ShotProductionView(
        id=row["id"], scene_id=row["scene_id"], code=st.code, number=int(row["number"]), title=row.get("title") or "",
        framing=Framing(row.get("framing") or "MS"), duration_s=int(row["duration_s"]),
        start_s=int(row.get("start_s") or 0), sound_mode=SoundMode(row.get("sound_mode") or "ambient"),
        camera_link=CameraLink(row.get("camera_link") or "cut"),
        frame_strategy=FrameStrategy(row.get("frame_strategy") or "generate"),
        status=ShotStatus(row.get("status") or "draft"), version=int(row.get("version") or 1), lines=lines,
        canon_refs=st.canon_refs,
        design=DesignView(state=state, stale_reasons=[] if state == "missing" else st.design_reasons,
                          planner=str(design.get("planner") or ""), rationale=str(design.get("rationale") or ""),
                          designed_at=design.get("designed_at")),
        camera=CameraView(recommended=st.recommended, current=st.camera, changed=changed,
                          storyboard_note=storyboard_note(st.camera)),
        checks=checks,
        frame_prompt=frame_prompt(ir=row.get("ir") or {}, camera=st.camera, aspect_ratio=ld.aspect, cast=st.cast,
                                  recommended_framing=st.recommended.framing) if st.has_design else "",
        frames=frames, accepted_frame_id=st.accepted["id"] if st.accepted else None,
        prompt_lock=LockView(locked=bool(st.lock), reason=st.lock),
        prompt=_prompt_view(st.prompt, st.prompt_reasons) if st.prompt else None)


def scene_view(ld: Loaded) -> SceneProductionView:
    checks = camera_checks(ld.states)
    s = ld.scene
    return SceneProductionView(id=s["id"], production_id=s["production_id"], episode_id=s["episode_id"],
                               number=int(s["number"]), heading=s.get("heading") or "", title=s.get("title") or "",
                               status=SceneStatus(s["status"]), approved=ld.approved, aspect_ratio=ld.aspect,
                               shots=[shot_view(ld, st, checks[st.id]) for st in ld.states])


def _require_approved(ld: Loaded) -> None:
    if not ld.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_APPROVED)


async def _audit(repos: Repos, access: ProductionAccess, action: str, entity: str, entity_id: str,
                 diff: dict[str, Any] | None = None) -> None:
    await repos.audit.record(action=action, entity=entity, entity_id=entity_id, actor_user_id=access.user.id,
                             production_id=access.production_id, diff=diff)


# ── reads ──────────────────────────────────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/production", response_model=SceneProductionView)
async def get_scene_production(production_id: UUID, scene_id: UUID, access: CanView,
                               repos: ReposDep) -> SceneProductionView:
    return scene_view(await load(repos, access, scene_id))


@router.get("/shots/{shot_id}", response_model=ShotProductionView)
async def get_shot(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep) -> ShotProductionView:
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


@router.get("/shots/{shot_id}/prompt", response_model=PromptView)
async def get_prompt(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep) -> PromptView:
    _, st = await load_shot(repos, access, shot_id)
    if st.prompt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This shot has no prompt yet.")
    return _prompt_view(st.prompt, st.prompt_reasons)


@router.get("/shots/{shot_id}/prompts", response_model=list[PromptView])
async def list_prompts(production_id: UUID, shot_id: UUID, access: CanView, repos: ReposDep) -> list[PromptView]:
    _, st = await load_shot(repos, access, shot_id)
    rows = await repos.prompts.list(shot_id)
    return [_prompt_view(r, st.prompt_reasons if i == 0 else ["A newer version exists."]) for i, r in enumerate(rows)]


# ── design and camera ──────────────────────────────────────────────────────────────────────


@router.post("/scenes/{scene_id}/design", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def design_scene(production_id: UUID, scene_id: UUID, body: DesignRequest, access: CanGenerate,
                       repos: ReposDep) -> Started:
    ld = await load(repos, access, scene_id)
    _require_approved(ld)
    if not ld.states:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no shots yet.")
    job_id = await task_manager.dispatch(JobKind.SHOT_PRODUCE, repos, actor_user_id=access.user.id,
                                         production_id=production_id, request={"scene_id": str(scene_id)},
                                         state={"mode": "design", "scene_ids": [str(scene_id)], "force": body.force})
    await _audit(repos, access, "scene.design", "scene", str(scene_id), {"job_id": str(job_id), "force": body.force})
    return Started(job_id=job_id)


@router.patch("/shots/{shot_id}/camera", response_model=ShotProductionView)
async def update_camera(production_id: UUID, shot_id: UUID, body: CameraUpdate, access: CanGenerate,
                        repos: ReposDep) -> ShotProductionView:
    """Only the fields sent change. A value equal to the recommendation, or null, clears the
    person's change, so a later re-design can update that field again."""
    ld, st = await load_shot(repos, access, shot_id)
    _require_approved(ld)
    overrides = dict(st.row.get("camera_overrides") or {})
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is None or value == getattr(st.recommended, key):
            overrides.pop(key, None)
        else:
            overrides[key] = value
    await repos.shots.update(shot_id, {"camera_overrides": overrides})
    await _audit(repos, access, "shot.camera", "shot", str(shot_id),
                 {k: getattr(body, k) for k in body.model_fields_set})
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


# ── frames ─────────────────────────────────────────────────────────────────────────────────


async def _start_frames(repos: Repos, access: ProductionAccess, ld: Loaded, targets: list[ShotState],
                        count: int) -> Started:
    """Frame rows first (the panel shows them at once), then one job: designs that are missing
    or out of date are made first (shot_producer), then every frame is painted (frame_render)."""
    pid = access.production_id
    rows = [{"id": str(uuid4()), "production_id": str(pid), "shot_id": st.id, "status": "queued",
             "created_by": str(access.user.id)} for st in targets for _ in range(count)]
    await repos.frames.create_many(rows)
    frame_ids = [r["id"] for r in rows]
    needs_design = [st.id for st in targets if st.design_reasons]
    state: dict[str, Any] = {"frame_ids": frame_ids}
    pipeline = [JobKind.FRAME_RENDER]
    if needs_design:
        state.update(mode="design", shot_ids=needs_design)
        pipeline = [JobKind.SHOT_PRODUCE, JobKind.FRAME_RENDER]
    try:
        job_id = await task_manager.dispatch(JobKind.FRAME_RENDER, repos, actor_user_id=access.user.id,
                                             production_id=pid, request={"scene_id": str(ld.scene["id"]),
                                                                         "frames": len(frame_ids)},
                                             state=state, pipeline=pipeline)
    except RuntimeError:
        await repos.frames.update_many(frame_ids, {"status": "failed", "error": "The job could not be started."})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Frames could not be started. Try again.") from None
    await repos.frames.update_many(frame_ids, {"job_id": str(job_id)})
    await _audit(repos, access, "frames.request", "scene", str(ld.scene["id"]),
                 {"job_id": str(job_id), "shots": [st.code for st in targets], "count": count})
    return Started(job_id=job_id, frame_ids=[UUID(f) for f in frame_ids])


def _carried(st: ShotState, ld: Loaded) -> str:
    prev = next((s for s in ld.states if int(s.row["number"]) == int(st.row["number"]) - 1), None)
    return (f"{st.code} carries on from {prev.code if prev else 'the previous shot'}'s take: its first frame is "
            "that take's last frame.")


@router.post("/shots/{shot_id}/frames", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_frames(production_id: UUID, shot_id: UUID, body: FramesRequest, access: CanGenerate,
                         repos: ReposDep) -> Started:
    ld, st = await load_shot(repos, access, shot_id)
    _require_approved(ld)
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        raise HTTPException(status.HTTP_409_CONFLICT, _carried(st, ld))
    return await _start_frames(repos, access, ld, [st], body.count)


@router.post("/scenes/{scene_id}/frames", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_scene_frames(production_id: UUID, scene_id: UUID, body: SceneFramesRequest, access: CanGenerate,
                               repos: ReposDep) -> Started:
    ld = await load(repos, access, scene_id)
    _require_approved(ld)
    def has_current_frame(st: ShotState) -> bool:
        return st.accepted is not None and not st.frame_reasons.get(str(st.accepted["id"]))

    targets = [st for st in ld.states if st.row.get("frame_strategy") != FrameStrategy.CARRY_LAST_FRAME
               and not (body.only_missing and has_current_frame(st))]
    if not targets:
        raise HTTPException(status.HTTP_409_CONFLICT, "Every shot that needs a first frame has one.")
    return await _start_frames(repos, access, ld, targets, body.count)


async def _frame(repos: Repos, production_id: UUID, frame_id: UUID) -> Row:
    frame = await repos.frames.get(production_id, frame_id)
    if frame is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found.")
    return frame


@router.post("/frames/{frame_id}/accept", response_model=ShotProductionView)
async def accept_frame(production_id: UUID, frame_id: UUID, access: CanGenerate, repos: ReposDep) -> ShotProductionView:
    frame = await _frame(repos, production_id, frame_id)
    ld, st = await load_shot(repos, access, UUID(str(frame["shot_id"])))
    _require_approved(ld)
    if frame["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a finished frame can be accepted.")
    if st.frame_reasons.get(str(frame_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This frame was made for an earlier version of the shot: "
                            + " ".join(st.frame_reasons[str(frame_id)]))
    if not await repos.frames.accept(UUID(st.id), frame_id, access.user.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone accepted another frame meanwhile. Reload the shot.")
    await repos.frames.update_many([str(frame_id)], {"rejected_reason": None})
    if st.row.get("status") == ShotStatus.DRAFT:
        await repos.shots.update(UUID(st.id), {"status": ShotStatus.FRAME.value})
    await _audit(repos, access, "frame.accept", "frame", str(frame_id), {"shot_id": st.id})
    ld, st = await load_shot(repos, access, UUID(st.id))
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


@router.post("/frames/{frame_id}/reject", response_model=ShotProductionView)
async def reject_frame(production_id: UUID, frame_id: UUID, body: RejectRequest, access: CanGenerate,
                       repos: ReposDep) -> ShotProductionView:
    frame = await _frame(repos, production_id, frame_id)
    ld, st = await load_shot(repos, access, UUID(str(frame["shot_id"])))
    if frame.get("accepted_at"):
        await repos.frames.unaccept(frame_id)
        if st.row.get("status") == ShotStatus.FRAME:
            await repos.shots.update(UUID(st.id), {"status": ShotStatus.DRAFT.value})
    await repos.frames.update_many([str(frame_id)], {"rejected_reason": body.reason.strip() or "Rejected"})
    await _audit(repos, access, "frame.reject", "frame", str(frame_id), {"shot_id": st.id, "reason": body.reason})
    ld, st = await load_shot(repos, access, UUID(st.id))
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


# ── prompts ────────────────────────────────────────────────────────────────────────────────


async def _start_prompts(repos: Repos, access: ProductionAccess, ld: Loaded, targets: list[ShotState]) -> Started:
    job_id = await task_manager.dispatch(JobKind.SHOT_PRODUCE, repos, actor_user_id=access.user.id,
                                         production_id=access.production_id,
                                         request={"scene_id": str(ld.scene["id"]), "prompts": len(targets)},
                                         state={"mode": "prompt", "shot_ids": [st.id for st in targets]})
    await _audit(repos, access, "prompts.request", "scene", str(ld.scene["id"]),
                 {"job_id": str(job_id), "shots": [st.code for st in targets]})
    return Started(job_id=job_id)


@router.post("/shots/{shot_id}/prompt", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_prompt(production_id: UUID, shot_id: UUID, access: CanGenerate, repos: ReposDep) -> Started:
    ld, st = await load_shot(repos, access, shot_id)
    if st.lock:
        raise HTTPException(status.HTTP_409_CONFLICT, st.lock)
    return await _start_prompts(repos, access, ld, [st])


@router.post("/scenes/{scene_id}/prompts", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_scene_prompts(production_id: UUID, scene_id: UUID, access: CanGenerate, repos: ReposDep) -> Started:
    ld = await load(repos, access, scene_id)
    _require_approved(ld)
    targets = [st for st in ld.states if not st.lock]
    if not targets:
        raise HTTPException(status.HTTP_409_CONFLICT, "No shot is ready for a prompt. Accept first frames first.")
    return await _start_prompts(repos, access, ld, targets)


# ── a person's own frame ───────────────────────────────────────────────────────────────────

MAX_FRAME_BYTES = 15 * 1024 * 1024  # the frames bucket's limit
_IMAGE_KINDS = ((b"\x89PNG\r\n\x1a\n", "png", "image/png"), (b"\xff\xd8\xff", "jpg", "image/jpeg"))


def _image_kind(data: bytes) -> tuple[str, str] | None:
    """By content, not by the name or type the browser sent: PNG, JPEG or WebP."""
    for magic, ext, mime in _IMAGE_KINDS:
        if data.startswith(magic):
            return ext, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


@router.post("/shots/{shot_id}/frames/upload", response_model=ShotProductionView,
             status_code=status.HTTP_201_CREATED)
async def upload_frame(production_id: UUID, shot_id: UUID, file: Annotated[UploadFile, File()],
                       access: CanGenerate, repos: ReposDep) -> ShotProductionView:
    """A first frame a person made elsewhere. It is pinned to the shot as it is now, like a
    painted one, so it goes out of date the same way."""
    ld, st = await load_shot(repos, access, shot_id)
    _require_approved(ld)
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        raise HTTPException(status.HTTP_409_CONFLICT, _carried(st, ld))
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data += chunk
        if len(data) > MAX_FRAME_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Frames can be at most 15 MB.")
    kind = _image_kind(bytes(data))
    if kind is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload a PNG, JPEG or WebP image.")
    ext, mime = kind
    frame_id = str(uuid4())
    path = f"{production_id}/{shot_id}/{frame_id}.{ext}"
    await repos.storage.upload("frames", path, bytes(data), mime)
    await repos.frames.create_many([{"id": frame_id, "production_id": str(production_id), "shot_id": str(shot_id),
                                     "status": "done", "storage_path": path, "prompt": "Uploaded by a person.",
                                     "pins": st.pins.model_dump(), "created_by": str(access.user.id)}])
    await _audit(repos, access, "frame.upload", "frame", frame_id, {"shot_id": str(shot_id), "bytes": len(data)})
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])
