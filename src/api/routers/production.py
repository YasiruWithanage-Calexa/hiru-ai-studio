"""Screen 3d, the Production panel: a scene's shots with their camera, first frames and video
prompt (PLAN.md §10, §13 Phase 4). Rules in `api/services/production.py`.

    GET   .../scenes/{id}/production      every shot of the scene, as the panel draws it
    GET   .../shots/{id}                  one shot
    POST  .../scenes/{id}/design          camera recommendations for the scene (job)
    PATCH .../shots/{id}/camera           a person's camera (null = back to the recommendation)
    PATCH .../shots/{id}/intent           a person's intent: what the shot is for, who is seen
    PATCH .../scenes/{id}/coverage        a person's coverage plan for the scene
    POST  .../shots/{id}/frames           first frames for one shot (job): `stage` draft (low quality) or final
                                          (medium); a final may be `from_draft` (the accepted draft is a reference)
    POST  .../scenes/{id}/frames          first frames for every shot that needs one (job)
    POST  .../shots/{id}/frames/upload    a frame a person made elsewhere
    POST  .../frames/{id}/accept|reject   picking is free; accepting a FINAL unlocks the prompt, accepting a draft only
                                          makes it the reference a final may be painted from
    POST  .../shots/{id}/prompt           a new prompt version (job), once a final frame is accepted
    POST  .../scenes/{id}/prompts         prompts for every shot whose prompt is open (job)

The scene LOCK (approval) closes the picture work: design, camera, intent, coverage and frames (make, upload,
accept, reject) need a scene that is NOT approved. Video prompts and videos work whether it is approved or not.
    GET   .../shots/{id}/prompt|prompts   the latest prompt / every version

Frames are streamed through `/files/{ticket}`; no storage URL reaches a browser. No costs are
shown anywhere (CLAUDE.md).
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, model_validator

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services import media_links, media_thumbs
from api.services.production import LOCKED, ShotState, camera_checks, scene_states
from api.workers import task_manager
from contracts.canon import look_wardrobe, looks_in_force
from contracts.frame_brief import (
    FrameBrief,
    PlannedReference,
    frame_brief,
    missing_references,
    opens_line,
    plan_references,
    reference_job,
    setup_frame,
)
from contracts.holding import hands_for
from contracts.jobs import JobKind
from contracts.producer import (
    CameraCheck,
    CameraField,
    CameraSettings,
    CameraUpdate,
    Check,
    FrameStage,
    PersonEdits,
    PromptSection,
    cast_in,
    frame_stage,
    storyboard_note,
)
from contracts.production import Framing, SceneStatus, ShotStatus
from contracts.roles import Permission
from contracts.staging import CoverageUpdate, IntentUpdate, ScenePlan, ShotIntent, unseen_sentence
from contracts.veo import ASPECT_RATIO, CameraLink, FrameStrategy, Orientation, SoundMode

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["production"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanGenerate = Annotated[ProductionAccess, Depends(require_permission(Permission.GENERATE))]
CanEditCanon = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_CANON))]
MAX_FRAMES_PER_REQUEST = 4


# ── views ──────────────────────────────────────────────────────────────────────────────────


class DesignView(BaseModel):
    state: str  # missing | current | stale
    stale_reasons: list[str]
    planner: str  # model | rules
    rationale: str  # the DoP's note: a person's own when `note_by_person`, else the DP's reason
    note_by_person: bool = False
    designed_at: str | None
    review: ReviewView | None = None  # the design review's notes on the first draft, when it had any


class IntentView(BaseModel):
    """What the shot is for and who the camera sees (`contracts.staging.ShotIntent`)."""

    purpose: str
    what_we_see: str
    emotional_beat: str
    on_screen: list[UUID]
    heard_only: list[UUID]
    voice_source: str
    by: str  # model | rules | person
    stale: bool  # written before the script or the shot changed


class PersonView(BaseModel):
    id: UUID
    code: str
    name: str
    seen: bool


class CoverageView(BaseModel):
    axis: str
    motif: str
    progression: str
    by: str
    stale: bool


class ReviewView(BaseModel):
    notes: list[str]
    revised: list[str]


class CameraView(BaseModel):
    recommended: CameraSettings
    current: CameraSettings
    changed: list[CameraField]  # fields a person changed
    storyboard_note: str  # "50mm · dolly in"


class FrameView(BaseModel):
    id: UUID
    label: str  # "First frame 2", or "Draft 2" for a draft
    stage: FrameStage  # draft = low quality, a reference only; final = medium quality, what opens the video prompt
    draft_id: UUID | None  # the accepted draft this final was painted from (None: painted without one)
    status: str  # queued | running | done | failed | refused
    url: str | None  # /files/{ticket}, never a storage URL
    thumb_url: str | None = None  # the 640 px WebP beside it: for tiles (may 404 for an older frame: use `url`)
    file_key: str | None = None  # names this file for ever (the URL changes every hour): one browser copy per key
    error: str | None
    rejected_reason: str | None
    accepted: bool
    stale: bool
    stale_reasons: list[str]
    created_at: str
    checks: list[Check] = Field(default_factory=list)  # a missing sheet; what a vision model saw


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


class BriefSectionView(BaseModel):
    """One section of the first frame's brief (plan/2026-11-11b): what it says and where its words came from."""

    key: str
    title: str
    text: str
    sources: list[str]


class FrameReferenceView(BaseModel):
    """One picture the next frame is painted against, in order, with its job; `missing` = wanted but there is none."""

    label: str
    role: str  # look | character | place | prop | setup
    name: str
    job: str
    missing: bool


class SetupFrameUpdate(BaseModel):
    off: bool  # true: never attach the same-setup frame to this shot


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
    people: list[PersonView]  # everyone in the shot; `seen` false = only heard
    intent: IntentView | None
    design: DesignView
    camera: CameraView
    checks: list[CameraCheck]
    frame_prompt: str  # what the next frame will be asked for ("" until designed): the exact text the renderer sends
    frame_brief: list[BriefSectionView] = Field(default_factory=list)  # the same prompt by section
    frame_references: list[FrameReferenceView] = Field(default_factory=list)  # the pictures it is painted against
    frame_missing: list[str] = Field(default_factory=list)  # pictures it wants but has none for, in words
    setup_frame_off: bool = False  # a person turned off the same-setup frame for this shot
    frame_polished: bool = False  # some of the frame prompt is in the prompt writer's words (plan/2026-11-11c)
    frames: list[FrameView]  # the finals (uploads and carried frames too)
    accepted_frame_id: UUID | None
    drafts: list[FrameView]  # low-quality drafts, newest last
    accepted_draft_id: UUID | None
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
    coverage: CoverageView | None
    shots: list[ShotProductionView]


class Started(BaseModel):
    job_id: UUID
    frame_ids: list[UUID] = Field(default_factory=list)


class DesignRequest(BaseModel):
    force: bool = False  # re-design shots whose design is still current


class FramesBase(BaseModel):
    count: int = Field(default=1, ge=1, le=MAX_FRAMES_PER_REQUEST)


class FramesRequest(FramesBase):
    stage: FrameStage = FrameStage.FINAL
    from_draft: bool = False  # a final only: attach the shot's accepted draft as a reference

    @model_validator(mode="after")
    def _draft_is_not_from_a_draft(self) -> FramesRequest:
        if self.from_draft and self.stage != FrameStage.FINAL:
            raise ValueError("only a final can be painted from a draft")
        return self


class SceneFramesRequest(FramesBase):
    only_missing: bool = True  # skip shots that already have what this stage makes (see request_scene_frames)
    stage: FrameStage = FrameStage.FINAL  # draft = low-quality pictures to settle the look, final = first frames


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


# ── loading ────────────────────────────────────────────────────────────────────────────────


class Loaded:
    def __init__(self, production: Row, scene: Row, states: list[ShotState], lines: list[Row],
                 canon: list[Row] | None = None, looks: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.production, self.scene, self.states, self.lines = production, scene, states, lines
        self.canon: list[Row] = canon or []  # the production's cards, as read for these states
        self.looks: Mapping[str, Mapping[str, Any]] = looks or {}  # character id → the look the scene uses

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
    frames, prompts, episode, all_looks, picks = await asyncio.gather(
        repos.frames.list_for_shots(ids), repos.prompts.latest_for_shots(ids),
        repos.episodes.get(production_id, UUID(str(scene["episode_id"]))),
        repos.looks.list_for_production(production_id), repos.scene_looks.list(scene_id))
    looks = looks_in_force(all_looks, picks, int(episode["number"]) if episode else None)
    states = scene_states(scene, shots, lines, canon, frames, prompts, looks)
    return Loaded(access.production, scene, states, lines, canon, looks)


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


def _checks(raw: Any) -> list[Check]:
    out = []
    for c in raw if isinstance(raw, list) else []:
        try:
            out.append(Check.model_validate(c))
        except ValueError:
            continue
    return out


def _intent_view(st: ShotState) -> IntentView | None:
    it = st.intent
    if it is None:
        return None
    return IntentView(purpose=it.purpose, what_we_see=it.what_we_see, emotional_beat=it.emotional_beat,
                      on_screen=[UUID(c) for c in st.staged.on_screen],
                      heard_only=[UUID(c) for c in st.staged.heard_only],
                      voice_source=st.staged.voice_source, by=it.by, stale=st.intent_stale)


def _review_view(design: Row) -> ReviewView | None:
    raw = design.get("review")
    if not isinstance(raw, dict) or not raw.get("notes"):
        return None
    return ReviewView(notes=[str(n) for n in raw.get("notes") or []],
                      revised=[str(r) for r in raw.get("revised") or []])


def coverage_view(scene: Row) -> CoverageView | None:
    plan = ScenePlan.of(scene)
    if plan is None:
        return None
    return CoverageView(axis=plan.axis, motif=plan.motif, progression=plan.progression, by=plan.by,
                        stale=plan.by != "person" and plan.made_for != int(scene.get("script_version") or 1))


def frame_plan(ld: Loaded, st: ShotState) -> tuple[FrameBrief, list[PlannedReference]]:
    """The next final frame as the renderer will make it (`hiru_ai.steps.frame_compose.World.brief`): the same pictures
    in the same order, the same people dressed in the looks the scene uses, the same hands and opening state. A draft
    is attached only when a person paints from it, so it is not part of this preview."""
    accepted = {s.id: s.accepted for s in ld.states if s.accepted}
    planned = plan_references(ld.scene, st.row, ld.canon, st.staged.on_screen, ld.looks,
                              setup=setup_frame(st.row, [s.row for s in ld.states], accepted))
    labels = [p.label for p in planned if p.choices]
    seen = [c.model_copy(update={"look": look_wardrobe(ld.looks[c.id])}) if c.id in ld.looks else c for c in st.seen]
    hands = hands_for(ld.scene, st.row, [c.name for c in st.seen]).sentence
    brief = frame_brief(ir=st.row.get("ir") or {}, camera=st.camera, aspect_ratio=ld.aspect, cast=seen,
                        references=labels, recommended=st.recommended,
                        unseen=unseen_sentence(st.staged, {c.id: c.name for c in st.cast}),
                        hands=" ".join(p for p in (hands, opens_line(st.row)) if p), scene=ld.scene, shot=st.row)
    return brief, planned


def _polished(brief: FrameBrief | None) -> bool:
    """Some of the first-frame prompt is in the prompt writer's words, still true to the shot (plan/2026-11-11c)."""
    return brief is not None and any("prompt_writer" in s["sources"] for s in brief.view())


def shot_view(ld: Loaded, st: ShotState, checks: list[CameraCheck]) -> ShotProductionView:
    row, design = st.row, st.row.get("design") or {}
    by_line = {str(ln["id"]): ln for ln in ld.lines}
    lines = []
    for item in st.items:
        ln = by_line.get(item.line_id or "") if item.is_line else None
        if ln:
            lines.append(ShotLine(id=ln["id"], speaker=ln["speaker"], character_id=ln.get("character_id"),
                                  text=ln["text"], delivery=ln.get("delivery") or "", words=int(ln.get("words") or 0),
                                  start_s=ln.get("start_s")))
    def frame_views(rows: list[Row], noun: str) -> list[FrameView]:
        views = []
        for n, f in enumerate(rows, start=1):
            reasons = st.frame_reasons.get(str(f["id"]), [])
            views.append(FrameView(
                id=f["id"], label=f"{noun} {n}", stage=frame_stage(f), draft_id=f.get("draft_id"),
                status=str(f["status"]),
                url=media_links.url("frames", str(f["storage_path"])) if f.get("storage_path") else None,
                thumb_url=media_links.thumb_url("frames", str(f["storage_path"])) if f.get("storage_path") else None,
                file_key=media_links.key("frames", str(f["storage_path"])) if f.get("storage_path") else None,
                error=f.get("error"), rejected_reason=f.get("rejected_reason"), accepted=bool(f.get("accepted_at")),
                stale=bool(reasons), stale_reasons=reasons, created_at=str(f["created_at"]),
                checks=_checks(f.get("checks"))))
        return views

    frames = frame_views(st.frames, "First frame")
    brief, planned = frame_plan(ld, st) if st.has_design else (None, [])
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
        people=[PersonView(id=UUID(c.id), code=c.code, name=c.name, seen=st.staged.visible(c.id)) for c in st.cast],
        intent=_intent_view(st),
        design=DesignView(state=state, stale_reasons=[] if state == "missing" else st.design_reasons,
                          planner=str(design.get("planner") or ""),
                          rationale=st.edits.dop_note or str(design.get("rationale") or ""),
                          note_by_person=bool(st.edits.dop_note), designed_at=design.get("designed_at"),
                          review=_review_view(design)),
        camera=CameraView(recommended=st.recommended, current=st.camera, changed=changed,
                          storyboard_note=storyboard_note(st.camera)),
        checks=checks,
        frame_prompt=brief.text() if brief else "",
        frame_brief=[BriefSectionView.model_validate(s) for s in brief.view()] if brief else [],
        frame_references=[FrameReferenceView(label=p.label or p.name, role=p.role, name=p.name,
                                             job=reference_job(p.label) if p.choices else "", missing=not p.choices)
                          for p in planned],
        frame_missing=missing_references(planned),
        setup_frame_off=st.edits.setup_frame_off,
        frame_polished=_polished(brief),
        frames=frames, accepted_frame_id=st.accepted["id"] if st.accepted else None,
        drafts=frame_views(st.drafts, "Draft"),
        accepted_draft_id=st.accepted_draft["id"] if st.accepted_draft else None,
        prompt_lock=LockView(locked=bool(st.lock), reason=st.lock),
        prompt=_prompt_view(st.prompt, st.prompt_reasons) if st.prompt else None)


def scene_view(ld: Loaded) -> SceneProductionView:
    checks = camera_checks(ld.states)
    s = ld.scene
    return SceneProductionView(id=s["id"], production_id=s["production_id"], episode_id=s["episode_id"],
                               number=int(s["number"]), heading=s.get("heading") or "", title=s.get("title") or "",
                               status=SceneStatus(s["status"]), approved=ld.approved, aspect_ratio=ld.aspect,
                               coverage=coverage_view(s),
                               shots=[shot_view(ld, st, checks[st.id]) for st in ld.states])


def _require_unlocked(ld: Loaded) -> None:
    """Picture work (design, camera, frames) is for a scene that is not approved yet: approving locks it."""
    if ld.approved:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCKED)


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
    _require_unlocked(ld)
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
    _require_unlocked(ld)
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


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


@router.patch("/shots/{shot_id}/intent", response_model=ShotProductionView)
async def update_intent(production_id: UUID, shot_id: UUID, body: IntentUpdate, access: CanGenerate,
                        repos: ReposDep) -> ShotProductionView:
    """A person's intent: only the fields sent change and the whole intent becomes theirs (an
    agent never replaces it). `reset` hands the shot back to the intent agent. Who is seen must be
    people already in the shot; the next design and frames follow it."""
    ld, st = await load_shot(repos, access, shot_id)
    _require_unlocked(ld)
    if body.reset:
        fields: dict[str, Any] = {}
    else:
        base = (st.intent or ShotIntent(on_screen=list(st.staged.on_screen), heard_only=list(st.staged.heard_only),
                                        voice_source=st.staged.voice_source)).model_dump()  # type: ignore[arg-type]
        for key in ("purpose", "what_we_see", "emotional_beat", "voice_source"):
            value = getattr(body, key)
            if value is not None:
                base[key] = " ".join(str(value).split())
        if body.on_screen is not None:
            in_shot = {c.id for c in st.cast}
            unknown = [c for c in body.on_screen if c not in in_shot]
            if unknown:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "Only people already in the shot can be on screen. Add them to the shot first.")
            base["on_screen"] = list(dict.fromkeys(body.on_screen))
            base["heard_only"] = [c for c in base.get("heard_only") or [] if c not in base["on_screen"]] or [
                c.id for c in st.cast if c.id not in base["on_screen"] and any(
                    x.speaker_id == c.id for x in st.items if x.is_line)]
        base.update(by="person", written_at=_now())
        fields = ShotIntent.model_validate(base).model_dump()
    await repos.shots.update(shot_id, {"intent": fields})
    await _audit(repos, access, "shot.intent", "shot", str(shot_id),
                 {"reset": True} if body.reset else body.model_dump(exclude_none=True, exclude={"reset"}))
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


async def _set_in_shot(repos: Repos, access: ProductionAccess, shot_id: UUID, entity_id: UUID, *,
                       add: bool) -> ShotProductionView:
    """Put one canon item in ONE shot, or take it out. Like the scene route, a mark is stored only when it
    differs from what the script gives the shot. Works on an approved scene: frames and prompts made before
    show as out of date (their pins no longer match), the shot is not unlocked."""
    ld, st = await load_shot(repos, access, shot_id)
    entity = await repos.canon.get(access.production_id, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Canon item not found.")
    eid = str(entity_id)
    characters = [c for c in ld.canon if c["kind"] == "character"]
    natural = {str(c) for c in cast_in(st.items, characters)}
    if ld.scene.get("location_id"):
        natural.add(str(ld.scene["location_id"]))
    edits = PersonEdits.of(st.row)
    cast = edits.cast
    before = (list(cast.add), list(cast.remove))
    if add:
        cast.remove = [i for i in cast.remove if i != eid]
        if eid not in natural and eid not in cast.add:
            cast.add.append(eid)
    else:
        cast.add = [i for i in cast.add if i != eid]
        if eid in natural and eid not in cast.remove:
            cast.remove.append(eid)
    if (cast.add, cast.remove) != before:
        await repos.shots.update(shot_id, {"person_edits": edits.dump()})
        await _audit(repos, access, "shot.canon_add" if add else "shot.canon_remove", "shot", str(shot_id),
                     {"canon": entity["name"]})
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


@router.put("/shots/{shot_id}/setup-frame", response_model=ShotProductionView)
async def set_setup_frame(production_id: UUID, shot_id: UUID, body: SetupFrameUpdate, access: CanGenerate,
                          repos: ReposDep) -> ShotProductionView:
    """Turn the same-setup frame off for this shot, or back on (plan/2026-11-11b §4.4). A person's mark: no agent
    writes it, and a re-design keeps it."""
    ld, st = await load_shot(repos, access, shot_id)
    _require_unlocked(ld)
    edits = PersonEdits.of(st.row)
    if edits.setup_frame_off != body.off:
        edits.setup_frame_off = body.off
        await repos.shots.update(shot_id, {"person_edits": edits.dump()})
        await _audit(repos, access, "shot.setup_frame", "shot", str(shot_id), {"off": body.off})
        ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


@router.put("/shots/{shot_id}/canon/{entity_id}", response_model=ShotProductionView)
async def add_shot_canon(production_id: UUID, shot_id: UUID, entity_id: UUID, access: CanEditCanon,
                         repos: ReposDep) -> ShotProductionView:
    """Put this canon item in this shot (or back, where it was taken out)."""
    return await _set_in_shot(repos, access, shot_id, entity_id, add=True)


@router.delete("/shots/{shot_id}/canon/{entity_id}", response_model=ShotProductionView)
async def remove_shot_canon(production_id: UUID, shot_id: UUID, entity_id: UUID, access: CanEditCanon,
                            repos: ReposDep) -> ShotProductionView:
    """Take this canon item out of this shot only; the rest of the scene keeps it."""
    return await _set_in_shot(repos, access, shot_id, entity_id, add=False)


@router.patch("/scenes/{scene_id}/coverage", response_model=SceneProductionView)
async def update_coverage(production_id: UUID, scene_id: UUID, body: CoverageUpdate, access: CanGenerate,
                          repos: ReposDep) -> SceneProductionView:
    """A person's coverage plan. `reset` hands it back to the intent agent."""
    ld = await load(repos, access, scene_id)
    _require_unlocked(ld)
    if body.reset:
        fields: dict[str, Any] = {}
    else:
        base = (ScenePlan.of(ld.scene) or ScenePlan()).model_dump()
        for key in ("axis", "motif", "progression"):
            value = getattr(body, key)
            if value is not None:
                base[key] = " ".join(str(value).split())
        base.update(by="person", made_for=int(ld.scene.get("script_version") or 1), written_at=_now())
        fields = ScenePlan.model_validate(base).model_dump()
    await repos.scenes.update(scene_id, {"coverage": fields})
    await _audit(repos, access, "scene.coverage", "scene", str(scene_id),
                 {"reset": True} if body.reset else body.model_dump(exclude_none=True, exclude={"reset"}))
    return scene_view(await load(repos, access, scene_id))


# ── frames ─────────────────────────────────────────────────────────────────────────────────


async def _start_frames(repos: Repos, access: ProductionAccess, ld: Loaded, targets: list[ShotState],
                        count: int, stage: FrameStage = FrameStage.FINAL, from_draft: bool = False) -> Started:
    """Frame rows first (the panel shows them at once), then one job: designs that are missing
    or out of date are made first (shot_producer), then every frame is painted (frame_render): a draft at low
    quality, a final at medium. A final `from_draft` carries the shot's accepted draft, which the job attaches as
    a reference (`draft_id` names it on the row, so a re-delivered job paints the same thing)."""
    pid = access.production_id
    rows = [{"id": str(uuid4()), "production_id": str(pid), "shot_id": st.id, "status": "queued",
             "stage": stage.value, "created_by": str(access.user.id),
             **({"draft_id": str(st.accepted_draft["id"])} if from_draft and st.accepted_draft else {})}
            for st in targets for _ in range(count)]
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
                 {"job_id": str(job_id), "shots": [st.code for st in targets], "count": count, "stage": stage.value,
                  "from_draft": from_draft})
    return Started(job_id=job_id, frame_ids=[UUID(f) for f in frame_ids])


def _carried(st: ShotState, ld: Loaded) -> str:
    prev = next((s for s in ld.states if int(s.row["number"]) == int(st.row["number"]) - 1), None)
    return (f"{st.code} carries on from {prev.code if prev else 'the previous shot'}'s take: its first frame is "
            "that take's last frame.")


@router.post("/shots/{shot_id}/frames", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_frames(production_id: UUID, shot_id: UUID, body: FramesRequest, access: CanGenerate,
                         repos: ReposDep) -> Started:
    ld, st = await load_shot(repos, access, shot_id)
    _require_unlocked(ld)
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        raise HTTPException(status.HTTP_409_CONFLICT, _carried(st, ld))
    if body.from_draft:
        draft = st.accepted_draft
        if draft is None or not draft.get("storage_path"):
            raise HTTPException(status.HTTP_409_CONFLICT, "Accept a draft first, or paint the final without one.")
        if st.frame_reasons.get(str(draft["id"])):
            raise HTTPException(status.HTTP_409_CONFLICT, "The accepted draft was made for an earlier version of the "
                                "shot: " + " ".join(st.frame_reasons[str(draft["id"])]))
    return await _start_frames(repos, access, ld, [st], body.count, body.stage, body.from_draft)


@router.post("/scenes/{scene_id}/frames", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_scene_frames(production_id: UUID, scene_id: UUID, body: SceneFramesRequest, access: CanGenerate,
                               repos: ReposDep) -> Started:
    ld = await load(repos, access, scene_id)
    _require_unlocked(ld)
    def has_current_frame(st: ShotState) -> bool:
        return st.accepted is not None and not st.frame_reasons.get(str(st.accepted["id"]))

    def has_current_draft(st: ShotState) -> bool:
        """A draft that is painting, or finished and still true to the shot; a failed or stale one does not count."""
        return any(d.get("status") in ("queued", "running") or
                   (d.get("status") == "done" and not st.frame_reasons.get(str(d["id"])))
                   for d in st.drafts)

    drafting = body.stage == FrameStage.DRAFT
    have = has_current_draft if drafting else has_current_frame
    targets = [st for st in ld.states if st.row.get("frame_strategy") != FrameStrategy.CARRY_LAST_FRAME
               and not (body.only_missing and have(st))]
    if not targets:
        raise HTTPException(status.HTTP_409_CONFLICT, "Every shot that needs a draft has one." if drafting
                            else "Every shot that needs a first frame has one.")
    return await _start_frames(repos, access, ld, targets, body.count, body.stage)


async def _frame(repos: Repos, production_id: UUID, frame_id: UUID) -> Row:
    frame = await repos.frames.get(production_id, frame_id)
    if frame is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found.")
    return frame


@router.post("/frames/{frame_id}/accept", response_model=ShotProductionView)
async def accept_frame(production_id: UUID, frame_id: UUID, access: CanGenerate, repos: ReposDep) -> ShotProductionView:
    frame = await _frame(repos, production_id, frame_id)
    ld, st = await load_shot(repos, access, UUID(str(frame["shot_id"])))
    _require_unlocked(ld)
    if frame["status"] != "done":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a finished frame can be accepted.")
    if st.frame_reasons.get(str(frame_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This frame was made for an earlier version of the shot: "
                            + " ".join(st.frame_reasons[str(frame_id)]))
    stage = frame_stage(frame)
    if not await repos.frames.accept(UUID(st.id), frame_id, access.user.id, stage.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone accepted another frame meanwhile. Reload the shot.")
    await repos.frames.update_many([str(frame_id)], {"rejected_reason": None})
    if stage == FrameStage.FINAL and st.row.get("status") == ShotStatus.DRAFT:  # a draft never opens the prompt
        await repos.shots.update(UUID(st.id), {"status": ShotStatus.FRAME.value})
    await _audit(repos, access, "frame.accept", "frame", str(frame_id), {"shot_id": st.id, "stage": stage.value})
    ld, st = await load_shot(repos, access, UUID(st.id))
    return shot_view(ld, st, camera_checks(ld.states)[st.id])


@router.post("/frames/{frame_id}/reject", response_model=ShotProductionView)
async def reject_frame(production_id: UUID, frame_id: UUID, body: RejectRequest, access: CanGenerate,
                       repos: ReposDep) -> ShotProductionView:
    frame = await _frame(repos, production_id, frame_id)
    ld, st = await load_shot(repos, access, UUID(str(frame["shot_id"])))
    _require_unlocked(ld)
    if frame.get("accepted_at"):
        await repos.frames.unaccept(frame_id)
        if frame_stage(frame) == FrameStage.FINAL and st.row.get("status") == ShotStatus.FRAME:
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


@router.post("/shots/{shot_id}/frame-prompt", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_frame_prompt(production_id: UUID, shot_id: UUID, access: CanGenerate, repos: ReposDep) -> Started:
    """Have the prompt writer reword this shot's first-frame prompt (plan/2026-11-11c). Code's prompt stays complete;
    the writer's words are used section by section where they keep every fact, and the shot screen shows the result.
    Picture work: refused on an approved scene, and before the shot has a camera design."""
    ld, st = await load_shot(repos, access, shot_id)
    _require_unlocked(ld)
    if not st.has_design:
        raise HTTPException(status.HTTP_409_CONFLICT, "This shot has no camera design yet. Design the scene first.")
    return await _start_frame_prompts(repos, access, ld, [st])


async def _start_frame_prompts(repos: Repos, access: ProductionAccess, ld: Loaded,
                               targets: list[ShotState]) -> Started:
    job_id = await task_manager.dispatch(JobKind.SHOT_PRODUCE, repos, actor_user_id=access.user.id,
                                         production_id=access.production_id,
                                         request={"scene_id": str(ld.scene["id"]), "frame_prompts": len(targets)},
                                         state={"mode": "frame_prompt", "shot_ids": [st.id for st in targets]})
    if len(targets) == 1:
        await _audit(repos, access, "frame_prompt.request", "shot", targets[0].id, {"job_id": str(job_id)})
    else:
        await _audit(repos, access, "frame_prompts.request", "scene", str(ld.scene["id"]),
                     {"job_id": str(job_id), "shots": [st.code for st in targets]})
    return Started(job_id=job_id)


class SceneFramePromptsRequest(BaseModel):
    only_missing: bool = True  # skip shots whose first-frame prompt is already in the writer's words and current


@router.post("/scenes/{scene_id}/frame-prompts", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_scene_frame_prompts(production_id: UUID, scene_id: UUID, body: SceneFramePromptsRequest,
                                      access: CanGenerate, repos: ReposDep) -> Started:
    """The prompt writer for every designed shot of the scene that paints its own first frame, in one job. A shot
    whose writer's words still fit it is left alone unless `only_missing` is off. Refused on an approved scene."""
    ld = await load(repos, access, scene_id)
    _require_unlocked(ld)
    targets = [st for st in ld.states if st.has_design
               and st.row.get("frame_strategy") != FrameStrategy.CARRY_LAST_FRAME
               and not (body.only_missing and _polished(frame_plan(ld, st)[0]))]
    if not targets:
        if not any(st.has_design for st in ld.states):
            raise HTTPException(status.HTTP_409_CONFLICT, "No shot has a camera design yet. Design the scene first.")
        raise HTTPException(status.HTTP_409_CONFLICT, "Every designed shot's first-frame prompt is already written.")
    return await _start_frame_prompts(repos, access, ld, targets)


@router.post("/scenes/{scene_id}/prompts", response_model=Started, status_code=status.HTTP_202_ACCEPTED)
async def request_scene_prompts(production_id: UUID, scene_id: UUID, access: CanGenerate, repos: ReposDep) -> Started:
    ld = await load(repos, access, scene_id)
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
    _require_unlocked(ld)
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
    await media_thumbs.store_with_thumb(repos, "frames", path, bytes(data), mime)
    await repos.frames.create_many([{"id": frame_id, "production_id": str(production_id), "shot_id": str(shot_id),
                                     "status": "done", "storage_path": path, "prompt": "Uploaded by a person.",
                                     "pins": st.pins.model_dump(), "created_by": str(access.user.id)}])
    await _audit(repos, access, "frame.upload", "frame", frame_id, {"shot_id": str(shot_id), "bytes": len(data)})
    ld, st = await load_shot(repos, access, shot_id)
    return shot_view(ld, st, camera_checks(ld.states)[st.id])
