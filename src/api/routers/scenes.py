"""Screen 2d, the Director panel: one scene with its script, shots and timeline, and the edits a
person makes by hand (PLAN.md §10). Chat edits go through `routers/director.py`.

* The TIMELINE (shot edges, when each line is spoken, what overruns, the envelope) is computed
  here by `contracts.shotplan` from the stored plan, so the Director and Production panels show
  the same numbers (PLAN.md §10 "Timeline numbers ... are computed on the server").
* A person's shot-length change LOCKS that length; the scene is re-timed around it and what no
  longer fits is reported, never trimmed. Shots keep their ids through every edit.
* An APPROVED scene is locked: unapprove it before changing it.
* Dialogue is changed only through the script (`PUT .../script`, Permission.EDIT_SCRIPT); the
  shot list follows the script, never the other way round.
"""
from __future__ import annotations

import asyncio
import difflib
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services.director import board
from api.workers import task_manager
from contracts import bridges, sceneplan, stagemap
from contracts import reading as scene_reading
from contracts.canon import CanonKind, name_key
from contracts.director import BoardMember, ScriptUpdate, ShotUpdate
from contracts.jobs import JobKind
from contracts.producer import PersonEdits, cast_in, shot_items
from contracts.production import BlockKind, Framing, ProductionSettings, SceneStatus, ShotStatus
from contracts.roles import Permission
from contracts.shotplan import FitResult, allowed_durations, fit, shot_clock
from contracts.veo import CameraLink, FrameStrategy, SoundMode

router = APIRouter(prefix="/v1/productions/{production_id}", tags=["scenes"])
ReposDep = Annotated[Repos, Depends(get_repos)]
CanView = Annotated[ProductionAccess, Depends(require_permission(Permission.VIEW))]
CanDirect = Annotated[ProductionAccess, Depends(require_permission(Permission.DIRECT))]
CanApprove = Annotated[ProductionAccess, Depends(require_permission(Permission.APPROVE_SCENE))]
CanWrite = Annotated[ProductionAccess, Depends(require_permission(Permission.EDIT_SCRIPT))]


# ── views ──────────────────────────────────────────────────────────────────────────────────


class BeatView(BaseModel):
    start_s: int
    end_s: int
    camera: str = ""
    director_line: str = ""
    action: str = ""


class HoldView(BaseModel):
    """A moment the scene's reading holds after block `block` (plan/2026-11-01d), inside the shot that has the block."""

    block: int
    seconds: float
    kind: str  # reaction | transition | atmosphere | button
    priority: int = 0  # 1 is never dropped by code; 2 and 3 go first when the scene is over its envelope
    who: str = ""  # whose face the hold is for


class PlaceView(BaseModel):
    """Where one person is while a shot starts (the staging map, plan/2026-11-01d Phase 4)."""

    who: str
    zone: str
    facing: str = ""
    frame_side: str = ""
    holding: str = ""


class StagingFindingView(BaseModel):
    """A staging problem to look at: `teleport` (a person is somewhere else with nothing to show the way),
    `line_crossed` (a cut swaps two people's sides of the frame) or `eyeline` (a shot and reverse shot look the same
    way)."""

    code: str
    message: str
    block: int | None = None
    shot_id: UUID | None = None
    who: list[str] = []
    zone: str = ""


class ShotView(BaseModel):
    id: UUID
    code: str  # "S01"
    number: int
    title: str
    framing: Framing
    duration_s: int
    duration_locked: bool  # a person set this length
    start_s: int
    end_s: int
    sound_mode: SoundMode
    camera_link: CameraLink
    frame_strategy: FrameStrategy
    speaker_id: UUID | None
    speaker: str  # the one visible speaker's canon name, when there is one
    beats: list[BeatView]
    block_start: int
    block_end: int
    word_target: int
    words: int
    line_ids: list[UUID]
    status: ShotStatus
    version: int
    picture_s: float = 0.0  # seconds its actions take to show
    need_s: float = 0.0  # seconds it needs to show them and say its lines
    crowded: bool = False  # it holds more than its length can show
    timeline: list[TimelineSlot] = []
    holds: list[HoldView] = []  # time the scene's reading gave it: a reaction, a look held, a last image
    places: list[PlaceView] = []  # where the people it shows are when it starts (empty without a staging map)


class LineView(BaseModel):
    """A spoken line, verbatim (Sinhala: render with `lang="si"`)."""

    id: UUID
    ord: int
    speaker: str
    character_id: UUID | None
    text: str
    delivery: str
    words: int
    shot_id: UUID | None
    beat_index: int | None
    # A translated line keeps the words it was written in (plan/2026-11-01c): shown on hover, restored on request.
    source_text: str | None = None
    source_lang: str | None = None
    start_s: float | None  # from the start of the scene
    end_s: float | None
    overrun_s: float  # how far it runs past its shot's cut (reported, never trimmed)


class ScriptBlockView(BaseModel):
    index: int
    kind: BlockKind
    text: str = ""  # action / sound / beat / cut text; a dialogue block's line is in `lines`
    line_id: UUID | None = None
    speaker: str = ""
    delivery: str = ""
    shot_id: UUID | None = None  # the shot this block plays in
    # How an action reads as a picture (plan/2026-11-01b): move | act | with_line | info | inner, how many
    # visible events it holds, the seconds it takes on screen, and whether the system added it as an
    # implied step ("Anudi answers the phone") that a person can remove.
    screen: str = ""
    events: int = 1
    picture_s: float = 0.0
    implied: bool = False
    bridge: str = ""


class TimelineSlot(BaseModel):
    """One block on a shot's own clock (seconds from the shot's start): a picture or a spoken line."""

    block: int
    kind: str  # "picture" | "line"
    start_s: float
    end_s: float


class IssueView(BaseModel):
    code: str  # line_overrun | word_budget | envelope | long_line | repaired | multi_speaker | crowded | split
    message: str
    shot_id: UUID | None = None
    line_id: UUID | None = None


class Timeline(BaseModel):
    total_s: int
    need_s: int = 0  # what the scene needs on screen to show and say everything in it
    crowded: list[int] = []  # numbers of the shots that hold more than they can show
    envelope_s: int
    over_envelope_s: int
    issues: list[IssueView]
    breath_s: float = 0.0  # seconds the scene gives to breath the reading asked for
    core_need_s: int | None = None  # what the scene needs without its optional breath (only when some was given up)


class CanonRef(BaseModel):
    id: UUID
    code: str
    name: str
    kind: CanonKind
    version: int | None  # the current card version
    locked: bool


class EpisodeRef(BaseModel):
    id: UUID
    number: int
    title: str


class SceneView(BaseModel):
    id: UUID
    production_id: UUID
    production_title: str
    episode: EpisodeRef
    number: int
    heading: str
    title: str
    note: str
    time_of_day: str
    location_id: UUID | None
    envelope_s: int
    status: SceneStatus
    script_version: int
    locked_at: datetime | None
    planner: str  # who planned the shots: rules | model | director | person
    critic_notes: list[str]
    script: list[ScriptBlockView]
    shots: list[ShotView]
    lines: list[LineView]
    timeline: Timeline
    canon: list[CanonRef]
    board: list[BoardMember]
    previous_scene_id: UUID | None
    next_scene_id: UUID | None
    reading: scene_reading.SceneReading | None = None  # what the scene is about (plan/2026-11-01d); a person's wins
    reading_stale: bool = False  # the script changed since it was written
    staging: stagemap.SceneStaging | None = None  # where everyone is (plan/2026-11-01d, Phase 4)
    staging_stale: bool = False
    staging_findings: list[StagingFindingView] = []  # teleports, crossed lines, eyelines found in code


class ResplitStarted(BaseModel):
    job_id: UUID


# ── loading and re-fitting ─────────────────────────────────────────────────────────────────


class Loaded:
    """A scene and what hangs off it, read once per request."""

    def __init__(self, production: Row, scene: Row, shots: list[Row], lines: list[Row]) -> None:
        self.production, self.scene, self.shots, self.lines = production, scene, shots, lines
        self.settings = ProductionSettings.model_validate(production.get("settings") or {})

    @property
    def fixed(self) -> int | None:
        return self.settings.fixed_shot_seconds

    def fit(self, plan: list[Row], script: list[Row] | None = None, lines: list[Row] | None = None,
            envelope_s: int | None = None) -> FitResult:
        items = sceneplan.scene_items(self.scene, self.lines if lines is None else lines, script)
        return fit(items, sceneplan.proposal_for(plan), fixed_seconds=self.fixed,
                   envelope_s=int(self.scene["envelope_s"]) if envelope_s is None else envelope_s)


async def load(repos: Repos, access: ProductionAccess, scene_id: UUID) -> Loaded:
    production_id = access.production_id
    scene, shots, lines = await asyncio.gather(
        repos.scenes.get(production_id, scene_id), repos.shots.list(production_id, scene_id),
        repos.lines.list(scene_id))
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    return Loaded(access.production, scene, shots, lines)


def _editable(scene: Row) -> None:
    if scene["status"] == SceneStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene is approved and locked. Unapprove it first.")


async def _save_fit(repos: Repos, ld: Loaded, plan: list[Row], result: FitResult, planner: str,
                    lines: list[Row] | None = None) -> None:
    shots, line_rows, removed = sceneplan.rows_after_fit(
        ld.scene, plan, result, ld.lines if lines is None else lines, before={str(s["id"]): s for s in ld.shots})
    await repos.shots.save_plan(shots, removed)
    await repos.lines.upsert(line_rows)
    await repos.scenes.update(UUID(str(ld.scene["id"])), {
        "status": SceneStatus.SPLIT.value, "fit_report": sceneplan.fit_report(result, planner)})


def natural_cast(ld: Loaded, canon_rows: list[Row]) -> dict[str, set[str]]:
    """Shot id → who and what the script puts in it: its speakers, who its action names, the place.
    What a person added or took out by hand (`PersonEdits.cast`) is not in it."""
    characters = [c for c in canon_rows if c["kind"] == CanonKind.CHARACTER.value]
    items = sceneplan.items_for(ld.scene.get("script") or [], ld.lines)
    place = {str(ld.scene["location_id"])} if ld.scene.get("location_id") else set()
    return {str(s["id"]): set(cast_in(shot_items(items, int(s["block_start"]), int(s["block_end"])), characters))
            | place for s in ld.shots}


def scene_canon_ids(ld: Loaded, canon_rows: list[Row]) -> list[str]:
    """The canon the scene uses, in order: its place, then who speaks in it, then what a person added
    to any of its shots. Whoever is in none of its shots any more (taken out by hand) is left out."""
    base = [str(ld.scene["location_id"])] if ld.scene.get("location_id") else []
    base += [str(ln["character_id"]) for ln in ld.lines if ln.get("character_id")]
    if not ld.shots:
        return list(dict.fromkeys(base))
    natural = natural_cast(ld, canon_rows)
    present: set[str] = set()
    added: list[str] = []
    for shot in ld.shots:
        edits = PersonEdits.of(shot)
        present |= (natural[str(shot["id"])] | set(edits.cast.add)) - set(edits.cast.remove)
        added += edits.cast.add
    return [cid for cid in dict.fromkeys([*base, *added]) if cid in present]


async def view(repos: Repos, access: ProductionAccess, scene_id: UUID) -> SceneView:
    production_id = access.production_id
    ld, canon_rows = await asyncio.gather(load(repos, access, scene_id), repos.canon.list(production_id))
    scene = ld.scene
    episode_id = UUID(str(scene["episode_id"]))
    episode, siblings = await asyncio.gather(repos.episodes.get(production_id, episode_id),
                                             repos.scenes.list(production_id, episode_id))
    assert episode is not None
    at = next(i for i, s in enumerate(siblings) if str(s["id"]) == str(scene_id))
    canon = {str(c["id"]): c for c in canon_rows}

    plan = sceneplan.plan_from_rows(ld.shots)
    result = ld.fit(plan) if plan else None
    kernel_items = sceneplan.scene_items(scene, ld.lines)
    cast_names = [str(c["name"]) for c in canon_rows if c["kind"] == CanonKind.CHARACTER]
    staging = stagemap.SceneStaging.of(scene)
    by_start = {int(s["block_start"]): s for s in ld.shots}
    shot_of_number: dict[int, UUID | None] = {}
    shots: list[ShotView] = []
    for f in result.shots if result else []:
        row = by_start.get(f.start)  # None only if the stored plan was not written by the kernel
        shot_of_number[f.number] = UUID(str(row["id"])) if row else None
        if row is None:
            continue
        speaker = canon.get(str(f.speaker_id)) if f.speaker_id else None
        shots.append(ShotView(
            id=row["id"], code=f"S{f.number:02d}", number=f.number, title=f.title, framing=Framing(f.framing),
            duration_s=f.duration_s, duration_locked=bool(row.get("duration_locked")), start_s=f.start_s,
            end_s=f.start_s + f.duration_s, sound_mode=f.sound_mode, camera_link=f.camera_link,
            frame_strategy=f.frame_strategy, speaker_id=UUID(f.speaker_id) if f.speaker_id else None,
            speaker=speaker["name"] if speaker else "",
            holds=[HoldView(block=b, seconds=sec, kind=kind, priority=kernel_items[b].hold_priority,
                            who=kernel_items[b].hold_who) for b, sec, kind in f.holds],
            places=[PlaceView(who=m.who, zone=m.zone, facing=m.facing, frame_side=m.frame_side, holding=m.holding)
                    for w in stagemap.people_in(kernel_items[f.start:f.end], cast_names)
                    if staging and (m := staging.mark_at(kernel_items, w, f.start)) is not None],
            beats=[BeatView(start_s=b0, end_s=b1, **{k: str(n.get(k, "")) for k in sceneplan.BEAT_TEXT})
                   for (b0, b1), n in zip(f.beats, _pad(row.get("beats") or [], len(f.beats)), strict=True)],
            block_start=f.start, block_end=f.end, word_target=f.word_target, words=f.words,
            line_ids=[UUID(x) for x in f.line_ids], status=ShotStatus(row.get("status") or "draft"),
            version=int(row.get("version") or 1), picture_s=f.picture_s, need_s=f.need_s,
            crowded=f.number in result.crowded if result else False,
            timeline=[TimelineSlot(block=s.index, kind="line" if s.is_line else "picture", start_s=round(s.start_s, 2),
                                   end_s=round(s.end_s, 2)) for s in shot_clock(kernel_items[f.start:f.end])[0]]))

    timed = {fl.line_id: fl for fl in result.lines} if result else {}
    lines = []
    for ln in ld.lines:
        fl = timed.get(str(ln["id"]))
        lines.append(LineView(
            id=ln["id"], ord=ln["ord"], speaker=ln["speaker"], character_id=ln.get("character_id"), text=ln["text"],
            delivery=ln.get("delivery") or "", words=fl.words if fl else int(ln.get("words") or 0),
            shot_id=shot_of_number.get(fl.shot_number) if fl else None, beat_index=fl.beat_index if fl else None,
            source_text=ln.get("source_text"), source_lang=ln.get("source_lang"),
            start_s=fl.start_s if fl else None, end_s=fl.end_s if fl else None,
            overrun_s=fl.overrun_s if fl else 0.0))

    line_by_id = {str(ln["id"]): ln for ln in ld.lines}
    shot_of_block = {b: s.id for s in shots for b in range(s.block_start, s.block_end)}
    script: list[ScriptBlockView] = []
    for block in scene.get("script") or []:
        kind = BlockKind(block.get("kind", "action"))
        said = line_by_id.get(str(block.get("line_id"))) if kind is BlockKind.DIALOGUE else None
        if kind is BlockKind.DIALOGUE and said is None:
            continue  # same rule as the kernel: a dangling line reference is not a block
        i = len(script)
        item = kernel_items[i] if i < len(kernel_items) else None
        picture = item is not None and item.kind == "action"
        script.append(ScriptBlockView(
            index=i, kind=kind, text="" if said else str(block.get("text", "")), line_id=said["id"] if said else None,
            speaker=said["speaker"] if said else "", delivery=(said.get("delivery") or "") if said else "",
            shot_id=shot_of_block.get(i), screen=item.screen if picture and item else "",
            events=item.events if picture and item else 1, picture_s=item.picture_s if item else 0.0,
            implied=bool(item and item.implied), bridge=item.bridge if item else ""))

    canon_refs = []
    for cid in scene_canon_ids(ld, canon_rows):
        c = canon.get(cid)
        if c:
            current = c.get("current") or {}
            canon_refs.append(CanonRef(id=c["id"], code=c["code"], name=c["name"], kind=c["kind"],
                                       version=current.get("version"), locked=bool(c.get("locked"))))

    issues = [IssueView(code=i.code, message=i.message, line_id=UUID(i.line_id) if i.line_id else None,
                        shot_id=shot_of_number.get(i.shot_number) if i.shot_number else None)
              for i in (result.issues if result else [])]
    report = scene.get("fit_report") or {}
    stored_reading = scene_reading.SceneReading.of(scene)
    members, _ = await board(repos, production_id)
    return SceneView(
        id=scene["id"], production_id=production_id, production_title=ld.production["title"],
        episode=EpisodeRef(id=episode["id"], number=episode["number"], title=episode.get("title") or ""),
        number=scene["number"], heading=scene.get("heading") or "", title=scene.get("title") or "",
        note=scene.get("note") or "", time_of_day=scene.get("time_of_day") or "", location_id=scene.get("location_id"),
        envelope_s=scene["envelope_s"], status=scene["status"], script_version=int(scene.get("script_version") or 1),
        locked_at=scene.get("locked_at"), planner=str(report.get("planner") or ""),
        critic_notes=[str(n) for n in report.get("critic_notes") or []], script=script, shots=shots, lines=lines,
        timeline=Timeline(total_s=result.total_s if result else 0, need_s=result.need_s if result else 0,
                          crowded=result.crowded if result else [], envelope_s=int(scene["envelope_s"]),
                          over_envelope_s=result.over_envelope_s if result else 0, issues=issues,
                          breath_s=round(result.breath_s, 2) if result else 0.0,
                          core_need_s=(report.get("breath") or {}).get("core_need_s")),
        canon=canon_refs, board=members,
        previous_scene_id=siblings[at - 1]["id"] if at > 0 else None,
        next_scene_id=siblings[at + 1]["id"] if at + 1 < len(siblings) else None,
        reading=stored_reading, reading_stale=bool(stored_reading and stored_reading.stale(
            sceneplan.items_for(scene.get("script") or [], ld.lines), int(scene.get("script_version") or 1))),
        staging=staging, staging_stale=bool(staging and staging.stale(
            sceneplan.items_for(scene.get("script") or [], ld.lines), int(scene.get("script_version") or 1))),
        staging_findings=staging_findings(staging, kernel_items, result, cast_names, shot_of_number))


def staging_findings(staging: stagemap.SceneStaging | None, items: list[Any], result: FitResult | None,
                     cast: list[str], shot_of_number: dict[int, UUID | None]) -> list[StagingFindingView]:
    """What the staging map's free checks find in this scene's plan, for the warning chips."""
    if staging is None:
        return []
    found = stagemap.teleports(staging, items, cast)
    if result is not None:
        found += stagemap.line_crossed(staging, items, result, cast) + stagemap.eyeline(staging, items, result)
    return [StagingFindingView(code=f.code, message=f.message, block=f.block,
                               shot_id=shot_of_number.get(f.shot) if f.shot else None, who=list(f.who), zone=f.zone)
            for f in found]


def _pad(beats: list[Row], n: int) -> list[Row]:
    return (list(beats) + [{}] * n)[:n]


# ── routes ─────────────────────────────────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}", response_model=SceneView)
async def get_scene(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> SceneView:
    return await view(repos, access, scene_id)


@router.patch("/shots/{shot_id}", response_model=SceneView)
async def update_shot(production_id: UUID, shot_id: UUID, body: ShotUpdate, access: CanDirect,
                      repos: ReposDep) -> SceneView:
    shot = await repos.shots.get(production_id, shot_id)
    if shot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shot not found.")
    ld = await load(repos, access, UUID(str(shot["scene_id"])))
    _editable(ld.scene)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return await view(repos, access, UUID(str(shot["scene_id"])))
    plan = sceneplan.plan_from_rows(ld.shots)
    target = next(p for p in plan if p["id"] == str(shot_id))
    if "duration_s" in fields:
        seconds = fields["duration_s"]
        if seconds is None:
            target["duration"], target["duration_locked"] = None, False
        elif seconds not in allowed_durations(ld.fixed):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Veo renders "
                                + ", ".join(str(d) for d in allowed_durations(ld.fixed)) + " second shots.")
        else:
            target["duration"], target["duration_locked"] = seconds, True
    if body.camera_link is CameraLink.CONTINUOUS and plan[0] is target:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The first shot has nothing before it to continue.")
    for key in ("framing", "camera_link", "title", "sound_mode"):
        if key in fields and fields[key] is not None:
            target[key] = getattr(fields[key], "value", fields[key])
    result = ld.fit(plan)
    if body.sound_mode is not None:
        fitted = next(f for f in result.shots if f.start == target["start"])
        if fitted.sound_mode is not body.sound_mode:
            reason = ("its sound follows the spoken lines in it" if fitted.words else
                      "a shot without words cannot be a spoken shot (Veo would invent speech)")
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                f"This shot stays {fitted.sound_mode.value}: {reason}.")
    await _save_fit(repos, ld, plan, result, "person")
    await repos.audit.record(action="shot.update", entity="shot", entity_id=str(shot_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={k: getattr(v, "value", v) for k, v in fields.items()})
    return await view(repos, access, UUID(str(shot["scene_id"])))


@router.post("/scenes/{scene_id}/resplit", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def resplit_scene(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep) -> ResplitStarted:
    """Plan the scene's shots again from its script (`script_split`). Replaces the shot list:
    lengths people set and the director's beat notes go with it."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    if not ld.scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    job_id = await task_manager.dispatch(JobKind.SCRIPT_SPLIT, repos, actor_user_id=access.user.id,
                                         production_id=production_id, request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)]})
    await repos.audit.record(action="scene.resplit", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id, diff={"job_id": str(job_id)})
    return ResplitStarted(job_id=job_id)


async def _episode_status(repos: Repos, production_id: UUID, episode_id: UUID) -> None:
    scenes = await repos.scenes.list(production_id, episode_id)
    statuses = [s["status"] for s in scenes]
    if statuses and all(s in (SceneStatus.SPLIT, SceneStatus.APPROVED) for s in statuses):
        done = all(s == SceneStatus.APPROVED for s in statuses)
        await repos.episodes.update(episode_id, {"status": "approved" if done else "ready"})


@router.post("/scenes/{scene_id}/approve", response_model=SceneView)
async def approve_scene(production_id: UUID, scene_id: UUID, access: CanApprove, repos: ReposDep) -> SceneView:
    ld = await load(repos, access, scene_id)
    if ld.scene["status"] != SceneStatus.APPROVED:
        if not ld.shots:
            raise HTTPException(status.HTTP_409_CONFLICT, "A scene needs shots before it can be approved.")
        await repos.scenes.update(scene_id, {"status": SceneStatus.APPROVED.value, "locked_by": str(access.user.id),
                                             "locked_at": datetime.now(UTC).isoformat()})
        await _episode_status(repos, production_id, UUID(str(ld.scene["episode_id"])))
        await repos.audit.record(action="scene.approve", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id)
    return await view(repos, access, scene_id)


@router.post("/scenes/{scene_id}/unapprove", response_model=SceneView)
async def unapprove_scene(production_id: UUID, scene_id: UUID, access: CanApprove, repos: ReposDep) -> SceneView:
    ld = await load(repos, access, scene_id)
    if ld.scene["status"] == SceneStatus.APPROVED:
        await repos.scenes.update(scene_id, {"status": SceneStatus.SPLIT.value, "locked_by": None, "locked_at": None})
        await _episode_status(repos, production_id, UUID(str(ld.scene["episode_id"])))
        await repos.audit.record(action="scene.unapprove", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id)
    return await view(repos, access, scene_id)


# ── the reading ────────────────────────────────────────────────────────────────────────────


class ReadingUpdate(BaseModel):
    """A person's reading of the scene (PUT). It replaces the stored one whole and is checked in code: an entry that
    points at a block that is not there, a person who is not in the scene, or a breath nothing earns is dropped."""

    model_config = ConfigDict(extra="forbid")

    about: str = Field(default="", max_length=400)
    value: scene_reading.Value = Field(default_factory=scene_reading.Value)
    tone: str = Field(default="", max_length=80)
    units: list[scene_reading.Unit] = []
    subtext: list[scene_reading.Subtext] = []
    breath: list[scene_reading.Breath] = []
    ending: str = Field(default="", max_length=400)


class ReadingView(BaseModel):
    reading: scene_reading.SceneReading | None
    stale: bool = False
    dropped: int = 0  # entries of the body that were checked away (PUT only)


async def _cast_names(repos: Repos, production_id: UUID) -> list[str]:
    return [str(c["name"]) for c in await repos.canon.list(production_id) if c["kind"] == CanonKind.CHARACTER]


async def _retime(repos: Repos, access: ProductionAccess, scene_id: UUID) -> None:
    """The reading changed: the stored shot list is timed again with the new holds. Lengths a person set stay; the
    others are sized again from what the shot now holds (a length the planner once asked for is not kept, or taking
    the reading away would leave every shot as long as the breath had made it)."""
    ld = await load(repos, access, scene_id)
    plan = [{**p, "duration": p["duration"] if p["duration_locked"] else None}
            for p in sceneplan.plan_from_rows(ld.shots)]
    if plan:
        planner = str((ld.scene.get("fit_report") or {}).get("planner") or "person")
        await _save_fit(repos, ld, plan, ld.fit(plan), planner)


@router.get("/scenes/{scene_id}/reading", response_model=ReadingView)
async def get_reading(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> ReadingView:
    ld = await load(repos, access, scene_id)
    stored = scene_reading.SceneReading.of(ld.scene)
    items = sceneplan.items_for(ld.scene.get("script") or [], ld.lines)
    version = int(ld.scene.get("script_version") or 1)
    return ReadingView(reading=stored, stale=bool(stored and stored.stale(items, version)))


@router.put("/scenes/{scene_id}/reading", response_model=ReadingView)
async def put_reading(production_id: UUID, scene_id: UUID, body: ReadingUpdate, access: CanDirect,
                      repos: ReposDep) -> ReadingView:
    """A person's reading. It is never replaced by the system after this (a script edit only marks it out of date)
    and it times the scene: its holds and turns are on the picture clock from now on."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    items = sceneplan.items_for(ld.scene.get("script") or [], ld.lines)
    version = int(ld.scene.get("script_version") or 1)
    raw = body.model_dump()
    made = scene_reading.validate(raw, items, await _cast_names(repos, production_id), version=version, by="person")
    made = made.model_copy(update={"written_at": datetime.now(UTC).isoformat(timespec="seconds")})
    asked = len(body.units) + len(body.subtext) + len(body.breath)
    said = {t.block for t in body.subtext}
    kept = len(made.units) + len([t for t in made.subtext if t.block in said]) + len(made.breath)
    await repos.scenes.update(scene_id, {"reading": made.model_dump(mode="json")})
    await _retime(repos, access, scene_id)
    await repos.audit.record(action="scene.reading", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"units": len(made.units), "breath": len(made.breath)})
    return ReadingView(reading=made, stale=False, dropped=max(0, asked - kept))


@router.delete("/scenes/{scene_id}/reading", response_model=ReadingView)
async def reset_reading(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep) -> ReadingView:
    """Hand the reading back to the system: the scene is timed without it until the next split writes a new one."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    await repos.scenes.update(scene_id, {"reading": {}})
    await _retime(repos, access, scene_id)
    await repos.audit.record(action="scene.reading.reset", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id)
    return ReadingView(reading=None)


# ── the staging map ────────────────────────────────────────────────────────────────────────


class StagingView(BaseModel):
    staging: stagemap.SceneStaging | None
    stale: bool = False
    findings: list[StagingFindingView] = []


@router.get("/scenes/{scene_id}/staging", response_model=StagingView)
async def get_staging(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> StagingView:
    """Where everyone is in the scene, and the teleports, crossed lines and eyelines code finds against its shots."""
    view_ = await view(repos, access, scene_id)
    return StagingView(staging=view_.staging, stale=view_.staging_stale, findings=view_.staging_findings)


@router.delete("/scenes/{scene_id}/staging", response_model=StagingView)
async def reset_staging(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep) -> StagingView:
    """Hand the map back to the system: the next split writes a new one. Steps it added to the script stay (remove
    one with `DELETE .../script/{index}`, and it is never added again)."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    await repos.scenes.update(scene_id, {"staging": {}})
    await repos.audit.record(action="scene.staging.reset", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id)
    return StagingView(staging=None)


# ── the script ─────────────────────────────────────────────────────────────────────────────


def _clean(text: str) -> str:
    """NFC, outer whitespace trimmed. ZWJ / ZWNJ are kept: Sinhala conjuncts need them."""
    return unicodedata.normalize("NFC", text).strip()


def _block_key(block: Row) -> tuple[str, str]:
    if block["kind"] == BlockKind.DIALOGUE:
        return ("dialogue", str(block["line_id"]))
    return (str(block["kind"]), str(block.get("text", "")))


def remap_plan(old_items: list[tuple[str, str]], new_items: list[tuple[str, str]], plan: list[Row]) -> list[Row]:
    """Carry the shot list across a script edit. Blocks are matched old → new (lines by id, the
    rest by text; an edited block in place counts as the same block). A shot starts at the new
    position of its first surviving block; new blocks join the shot before them; a shot whose
    blocks were all deleted is dropped."""
    moved: dict[int, int] = {}
    matcher = difflib.SequenceMatcher(a=old_items, b=new_items, autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal" or (tag == "replace" and a1 - a0 == b1 - b0):
            moved.update({a0 + k: b0 + k for k in range(a1 - a0)})
    out: list[Row] = []
    for shot in plan:
        starts = [moved[b] for b in range(int(shot["start"]), int(shot["end"])) if b in moved]
        if starts and (not out or min(starts) > out[-1]["start"]):
            out.append({**shot, "start": min(starts)})
    if not out or not new_items:
        return []
    out[0]["start"] = 0
    for here, nxt in zip(out, [*out[1:], None], strict=True):
        here["end"] = nxt["start"] if nxt else len(new_items)
    return out


@router.put("/scenes/{scene_id}/script", response_model=SceneView)
async def update_script(production_id: UUID, scene_id: UUID, body: ScriptUpdate, access: CanWrite,
                        repos: ReposDep) -> SceneView:
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    version = int(ld.scene.get("script_version") or 1)
    if body.script_version != version:
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone changed this script meanwhile. Reload it and "
                                                      "make your change again.")
    old_lines = {str(ln["id"]): ln for ln in ld.lines}
    unknown = [str(b.line_id) for b in body.blocks if b.line_id is not None and str(b.line_id) not in old_lines]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A line in the edit is not in this scene.")
    characters = [c for c in await repos.canon.list(production_id) if c["kind"] == CanonKind.CHARACTER]

    def character_for(speaker: str, old: Row | None) -> Any:
        if old is not None and name_key(old["speaker"]) == name_key(speaker):
            return old.get("character_id")
        key = name_key(speaker)
        return next((c["id"] for c in characters
                     if key in {name_key(n) for n in [c["name"], *(c.get("aliases") or [])]}), None)

    script: list[Row] = []
    lines: list[Row] = []
    for b in body.blocks:
        if b.kind is BlockKind.DIALOGUE:
            old = old_lines.get(str(b.line_id)) if b.line_id else None
            line_id = str(b.line_id) if b.line_id else str(uuid4())
            speaker = _clean(b.speaker)
            lines.append({"id": line_id, "production_id": str(production_id), "scene_id": str(scene_id),
                          "ord": len(lines), "speaker": speaker, "character_id": character_for(speaker, old),
                          "text": _clean(b.text), "delivery": _clean(b.delivery),
                          # a translated line keeps the words it was written in, whoever edits it next
                          **{k: old[k] for k in sceneplan.LINE_SOURCE if old and old.get(k)}})
            script.append({"kind": BlockKind.DIALOGUE.value, "text": "", "line_id": line_id})
        else:
            script.append({"kind": b.kind.value, "text": _clean(b.text), "line_id": None})

    script = bridges.carry(ld.scene.get("script") or [], script)  # readings and implied steps survive an edit
    await _replace_script(repos, access, ld, script, lines, version, [lid for lid in old_lines
                                                                       if lid not in {ln["id"] for ln in lines}])
    return await view(repos, access, scene_id)


async def _replace_script(repos: Repos, access: ProductionAccess, ld: Loaded, script: list[Row], lines: list[Row],
                          version: int, removed_lines: list[str]) -> None:
    """Store a changed script: carry the shot list across it and re-time it, or drop the shot list
    when none of the old script survives (Re-split plans it again)."""
    scene_id = UUID(str(ld.scene["id"]))
    production_id = access.production_id
    old_keys = [_block_key(_as_block(i)) for i in sceneplan.items_for(ld.scene.get("script") or [], ld.lines)]
    new_keys = [_block_key(_as_block(i)) for i in sceneplan.items_for(script, lines)]
    plan = remap_plan(old_keys, new_keys, sceneplan.plan_from_rows(ld.shots)) if ld.shots else []

    # Lines first (deleted ones go before new ones take their places), then the script, then
    # the shot list re-timed against the new words.
    await repos.lines.delete(removed_lines)
    if plan:
        result = ld.fit(plan, script, lines)
        await repos.scenes.update(scene_id, {"script": script, "script_version": version + 1})
        ld.lines = lines
        await _save_fit(repos, ld, plan, result, str((ld.scene.get("fit_report") or {}).get("planner") or "person"),
                        lines)
    else:  # no shot list yet, or none of its script survived: plan it with Re-split
        await repos.shots.save_plan([], [str(s["id"]) for s in ld.shots])
        await repos.lines.upsert([{**ln, "words": 0, "shot_id": None, "beat_index": None, "start_s": None,
                                   "overrun_s": 0} for ln in lines])
        await repos.scenes.update(scene_id, {"script": script, "script_version": version + 1,
                                             "status": SceneStatus.DRAFT.value, "fit_report": {}})
    await repos.audit.record(action="scene.script", entity="scene", entity_id=str(scene_id),
                             actor_user_id=access.user.id, production_id=production_id,
                             diff={"script_version": version + 1, "lines": len(lines),
                                   "lines_removed": len(removed_lines), "blocks": len(script)})


@router.delete("/scenes/{scene_id}/script/{index}", response_model=SceneView)
async def remove_implied_step(production_id: UUID, scene_id: UUID, index: int, access: CanWrite,
                              repos: ReposDep) -> SceneView:
    """Take out a step the system added to the script (an "Implied" block, `contracts.bridges`). The
    phone line it belonged to remembers, so a re-split never brings it back. Only an implied step can
    be removed here; anything else is changed through the script."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    blocks = [b for b in (ld.scene.get("script") or [])
              if not (b.get("kind") == BlockKind.DIALOGUE and str(b.get("line_id")) not in {
                  str(ln["id"]) for ln in ld.lines})]  # the positions the view numbers
    if not 0 <= index < len(blocks) or not blocks[index].get("implied"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That block is not an implied step.")
    stored = ld.scene.get("script") or []
    position = next(p for p, b in enumerate(stored) if b is blocks[index])
    script = bridges.skip_bridge(stored, position)
    await _replace_script(repos, access, ld, script, ld.lines, int(ld.scene.get("script_version") or 1), [])
    return await view(repos, access, scene_id)


def _as_block(item: Any) -> Row:
    return {"kind": item.kind, "text": item.text, "line_id": item.line_id}
