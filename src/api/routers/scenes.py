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

import difflib
import unicodedata
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps.authz import ProductionAccess, require_permission
from api.deps.db import get_repos
from api.repositories import Repos, Row
from api.services.director import board
from api.workers import task_manager
from contracts import sceneplan
from contracts.canon import CanonKind, name_key
from contracts.director import BoardMember, ScriptUpdate, ShotUpdate
from contracts.jobs import JobKind
from contracts.production import BlockKind, Framing, ProductionSettings, SceneStatus, ShotStatus
from contracts.roles import Permission
from contracts.shotplan import FitResult, allowed_durations, fit
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


class IssueView(BaseModel):
    code: str  # line_overrun | word_budget | envelope | long_line | repaired
    message: str
    shot_id: UUID | None = None
    line_id: UUID | None = None


class Timeline(BaseModel):
    total_s: int
    envelope_s: int
    over_envelope_s: int
    issues: list[IssueView]


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
        items = sceneplan.items_for(self.scene.get("script") or [] if script is None else script,
                                    self.lines if lines is None else lines)
        return fit(items, sceneplan.proposal_for(plan), fixed_seconds=self.fixed,
                   envelope_s=int(self.scene["envelope_s"]) if envelope_s is None else envelope_s)


async def load(repos: Repos, production_id: UUID, scene_id: UUID) -> Loaded:
    scene = await repos.scenes.get(production_id, scene_id)
    if scene is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scene not found.")
    production = await repos.productions.get(production_id)
    assert production is not None  # authz already found it
    return Loaded(production, scene, await repos.shots.list(production_id, scene_id), await repos.lines.list(scene_id))


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


async def view(repos: Repos, production_id: UUID, scene_id: UUID) -> SceneView:
    ld = await load(repos, production_id, scene_id)
    scene = ld.scene
    episode = await repos.episodes.get(production_id, UUID(str(scene["episode_id"])))
    assert episode is not None
    siblings = await repos.scenes.list(production_id, UUID(str(scene["episode_id"])))
    at = next(i for i, s in enumerate(siblings) if str(s["id"]) == str(scene_id))
    canon = {str(c["id"]): c for c in await repos.canon.list(production_id)}

    plan = sceneplan.plan_from_rows(ld.shots)
    result = ld.fit(plan) if plan else None
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
            beats=[BeatView(start_s=b0, end_s=b1, **{k: str(n.get(k, "")) for k in sceneplan.BEAT_TEXT})
                   for (b0, b1), n in zip(f.beats, _pad(row.get("beats") or [], len(f.beats)), strict=True)],
            block_start=f.start, block_end=f.end, word_target=f.word_target, words=f.words,
            line_ids=[UUID(x) for x in f.line_ids], status=ShotStatus(row.get("status") or "draft"),
            version=int(row.get("version") or 1)))

    timed = {fl.line_id: fl for fl in result.lines} if result else {}
    lines = []
    for ln in ld.lines:
        fl = timed.get(str(ln["id"]))
        lines.append(LineView(
            id=ln["id"], ord=ln["ord"], speaker=ln["speaker"], character_id=ln.get("character_id"), text=ln["text"],
            delivery=ln.get("delivery") or "", words=fl.words if fl else int(ln.get("words") or 0),
            shot_id=shot_of_number.get(fl.shot_number) if fl else None, beat_index=fl.beat_index if fl else None,
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
        script.append(ScriptBlockView(
            index=i, kind=kind, text="" if said else str(block.get("text", "")), line_id=said["id"] if said else None,
            speaker=said["speaker"] if said else "", delivery=(said.get("delivery") or "") if said else "",
            shot_id=shot_of_block.get(i)))

    refs = [str(scene["location_id"])] if scene.get("location_id") else []
    refs += [str(ln["character_id"]) for ln in ld.lines if ln.get("character_id")]
    canon_refs = []
    for cid in dict.fromkeys(refs):
        c = canon.get(cid)
        if c:
            current = c.get("current") or {}
            canon_refs.append(CanonRef(id=c["id"], code=c["code"], name=c["name"], kind=c["kind"],
                                       version=current.get("version"), locked=bool(c.get("locked"))))

    issues = [IssueView(code=i.code, message=i.message, line_id=UUID(i.line_id) if i.line_id else None,
                        shot_id=shot_of_number.get(i.shot_number) if i.shot_number else None)
              for i in (result.issues if result else [])]
    report = scene.get("fit_report") or {}
    members, _ = await board(repos, production_id)
    return SceneView(
        id=scene["id"], production_id=production_id, production_title=ld.production["title"],
        episode=EpisodeRef(id=episode["id"], number=episode["number"], title=episode.get("title") or ""),
        number=scene["number"], heading=scene.get("heading") or "", title=scene.get("title") or "",
        note=scene.get("note") or "", time_of_day=scene.get("time_of_day") or "", location_id=scene.get("location_id"),
        envelope_s=scene["envelope_s"], status=scene["status"], script_version=int(scene.get("script_version") or 1),
        locked_at=scene.get("locked_at"), planner=str(report.get("planner") or ""),
        critic_notes=[str(n) for n in report.get("critic_notes") or []], script=script, shots=shots, lines=lines,
        timeline=Timeline(total_s=result.total_s if result else 0, envelope_s=int(scene["envelope_s"]),
                          over_envelope_s=result.over_envelope_s if result else 0, issues=issues),
        canon=canon_refs, board=members,
        previous_scene_id=siblings[at - 1]["id"] if at > 0 else None,
        next_scene_id=siblings[at + 1]["id"] if at + 1 < len(siblings) else None)


def _pad(beats: list[Row], n: int) -> list[Row]:
    return (list(beats) + [{}] * n)[:n]


# ── routes ─────────────────────────────────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}", response_model=SceneView)
async def get_scene(production_id: UUID, scene_id: UUID, _: CanView, repos: ReposDep) -> SceneView:
    return await view(repos, production_id, scene_id)


@router.patch("/shots/{shot_id}", response_model=SceneView)
async def update_shot(production_id: UUID, shot_id: UUID, body: ShotUpdate, access: CanDirect,
                      repos: ReposDep) -> SceneView:
    shot = await repos.shots.get(production_id, shot_id)
    if shot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shot not found.")
    ld = await load(repos, production_id, UUID(str(shot["scene_id"])))
    _editable(ld.scene)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        return await view(repos, production_id, UUID(str(shot["scene_id"])))
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
    return await view(repos, production_id, UUID(str(shot["scene_id"])))


@router.post("/scenes/{scene_id}/resplit", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def resplit_scene(production_id: UUID, scene_id: UUID, access: CanDirect, repos: ReposDep) -> ResplitStarted:
    """Plan the scene's shots again from its script (`script_split`). Replaces the shot list:
    lengths people set and the director's beat notes go with it."""
    ld = await load(repos, production_id, scene_id)
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
    ld = await load(repos, production_id, scene_id)
    if ld.scene["status"] != SceneStatus.APPROVED:
        if not ld.shots:
            raise HTTPException(status.HTTP_409_CONFLICT, "A scene needs shots before it can be approved.")
        await repos.scenes.update(scene_id, {"status": SceneStatus.APPROVED.value, "locked_by": str(access.user.id),
                                             "locked_at": datetime.now(UTC).isoformat()})
        await _episode_status(repos, production_id, UUID(str(ld.scene["episode_id"])))
        await repos.audit.record(action="scene.approve", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id)
    return await view(repos, production_id, scene_id)


@router.post("/scenes/{scene_id}/unapprove", response_model=SceneView)
async def unapprove_scene(production_id: UUID, scene_id: UUID, access: CanApprove, repos: ReposDep) -> SceneView:
    ld = await load(repos, production_id, scene_id)
    if ld.scene["status"] == SceneStatus.APPROVED:
        await repos.scenes.update(scene_id, {"status": SceneStatus.SPLIT.value, "locked_by": None, "locked_at": None})
        await _episode_status(repos, production_id, UUID(str(ld.scene["episode_id"])))
        await repos.audit.record(action="scene.unapprove", entity="scene", entity_id=str(scene_id),
                                 actor_user_id=access.user.id, production_id=production_id)
    return await view(repos, production_id, scene_id)


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
    ld = await load(repos, production_id, scene_id)
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
                          "text": _clean(b.text), "delivery": _clean(b.delivery)})
            script.append({"kind": BlockKind.DIALOGUE.value, "text": "", "line_id": line_id})
        else:
            script.append({"kind": b.kind.value, "text": _clean(b.text), "line_id": None})

    removed_lines = [lid for lid in old_lines if lid not in {ln["id"] for ln in lines}]
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
    return await view(repos, production_id, scene_id)


def _as_block(item: Any) -> Row:
    return {"kind": item.kind, "text": item.text, "line_id": item.line_id}
