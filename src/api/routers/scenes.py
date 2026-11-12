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
from contracts.producer import PersonEdits, shot_items
from contracts.production import BlockKind, Framing, ProductionSettings, SceneStatus, ShotStatus
from contracts.roles import Permission
from contracts.shotplan import FitResult, allowed_durations, fit, shot_clock
from contracts.staging import ShotIntent, shot_cast
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
    planner: str = "classic"  # which planner made the shot: classic | adam (plan/2026-11-04b)
    # Shot Planner Raphael (plan/2026-11-08e): the clip a shot is in the bin ("" and 0 for another planner's shot)
    slate: str = ""
    role: str = ""
    priority: str = ""
    stage: int = 0
    anchor: list[str] = []
    blend: str = ""
    # What happens in the shot, in plain words (the Raphael clip's summary; "" for another planner's shot)
    summary: str = ""


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
    planner: str  # who planned the shots: rules | model | director | person | adam
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
    # How the script was read (plan/2026-11-06f decision 6): "pages" = the document reader read it from page images, so
    # its dialogue waits for a person to check it against the page; None = the rules read it.
    read_from: str | None = None
    read_confirmed_at: datetime | None = None


class ResplitStarted(BaseModel):
    job_id: UUID


class AdamView(BaseModel):
    """What Shot Planner Adam keeps for a scene (plan/2026-11-04b): `plan` is None for a scene it never planned."""

    scene_id: UUID
    planner: str  # classic | adam: who made the shots on the scene now
    # The plan as Adam stored it (`scenes.adam`), passed on as it is: this router knows nothing of its parts, so
    # removing Adam removes nothing here but these endpoints.
    plan: dict[str, Any] | None = None


class DavidView(BaseModel):
    """What Shot Planner David keeps for a scene (plan/2026-11-05e): `plan` is None for a scene it never planned."""

    scene_id: UUID
    planner: str  # classic | adam | david: who made the shots on the scene now
    # The plan as David stored it (`scenes.david`), passed on as it is: this router knows nothing of its parts, so
    # removing David removes nothing here but these endpoints.
    plan: dict[str, Any] | None = None


class DavidPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A person's note on the plan ("start closer on Anudi"): one repair call with the note as the problem, on the
    # plan as
    # it stands. Empty: David plans the scene again from the script.
    note: str = Field(default="", max_length=1000)


class JonathanView(BaseModel):
    """What Shot Planner Jonathan keeps for a scene (plan/2026-11-05e): `plan` is None for a scene it never planned."""

    scene_id: UUID
    planner: str  # classic | adam | david | jonathan: who made the shots on the scene now
    # The plan as Jonathan stored it (`scenes.jonathan`), passed on as it is: this router knows nothing of its parts, so
    # removing Jonathan removes nothing here but these endpoints.
    plan: dict[str, Any] | None = None


class JonathanPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A person's note on the plan ("start closer on Anudi"): one repair call with the note as the problem, on the
    # plan as
    # it stands. Empty: Jonathan plans the scene again from the script.
    note: str = Field(default="", max_length=1000)


class ShotStateView(BaseModel):
    """One Raphael shot's story and the state it opens and ends in (plan/2026-11-09), from its intent."""

    story: str = ""
    opens: str = ""
    ends: str = ""


class RaphaelView(BaseModel):
    """What Shot Planner Raphael keeps for a scene (plan/2026-11-08e): `result` is None for a scene it never planned."""

    scene_id: UUID
    planner: str  # classic | adam | david | jonathan | raphael: who made the shots on the scene now
    # The result as Raphael stored it (`scenes.raphael`), passed on as it is: this router knows nothing of its parts, so
    # removing Raphael removes nothing here but these endpoints.
    result: dict[str, Any] | None = None
    # The length cap the production plans with (a choice, plan §2.1) and the four choices a person may make for a run.
    default_cap: float = 2
    caps: list[float] = Field(default_factory=lambda: [1, 1.5, 2, 2.5, 3])
    # plan/2026-11-09 phase 8: the scene's state ledger, read by code. Each shot's story and the state it opens and
    # ends in, by slate (from the shot's intent); the state checks' reports (`result.left` rows with code "state").
    # Both empty for a scene with no state map.
    states: dict[str, ShotStateView] = Field(default_factory=dict)
    state_faults: list[dict[str, Any]] = Field(default_factory=list)



class RaphaelPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The length cap for this run, one of 1.5, 2, 2.5, 3 times the scene's given length. Empty: the production's.
    cap: float | None = None
    # A person's note on the scene ("keep it tighter"): it goes in the scene's context for the whole plan.
    note: str = Field(default="", max_length=1000)


class RaphaelCinematicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cap: float | None = None


class AdamPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # "restrained" | "intimate" | "heightened": plan the cards under that treatment (a switch keeps the analysis and the
    # treatments). Empty: Adam chooses, by the quick score on the treatments.
    treatment: str = Field(default="", pattern=r"^(|restrained|intimate|heightened)$")
    screening: bool = True  # the four critics and one revision; off is faster and cheaper


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
    # shot_cast, not cast_in: it also counts who the shot's intent puts on screen, so the scene's canon holds
    # everyone a shot pins (the interface lists a shot's canon from the scene's).
    return {str(s["id"]): set(shot_cast(shot_items(items, int(s["block_start"]), int(s["block_end"])), characters, s))
            | place for s in ld.shots}


def briefed_ids(packet_row: Row | None, scene: Row) -> list[str]:
    """plan/2026-11-12c Track B: the scene's canon by id from its packet (the breakdown's brief through the memory's
    map): the people on screen, not only speakers, and the things a camera sees. [] without a current packet."""
    if not packet_row or int(packet_row.get("script_version") or 0) != int(scene.get("script_version") or 1):
        return []
    canon = (packet_row.get("packet") or {}).get("canon") or {}
    return [str(i) for i in [*(canon.get("people") or []), *(canon.get("things") or [])] if i]


def scene_canon_ids(ld: Loaded, canon_rows: list[Row], briefed: list[str] | None = None) -> list[str]:
    """The canon the scene uses, in order: its place, then who speaks in it, then what a person added
    to any of its shots. Whoever is in none of its shots any more (taken out by hand) is left out. `briefed`: what
    the scene's breakdown brief adds by id (plan/2026-11-12c Track B), after the rest and kept even when no shot names
    it (a silent person on screen, a prop no line names)."""
    base = [str(ld.scene["location_id"])] if ld.scene.get("location_id") else []
    base += [str(ln["character_id"]) for ln in ld.lines if ln.get("character_id")]
    extra = [i for i in briefed or [] if i not in base]
    if not ld.shots:
        return list(dict.fromkeys([*base, *extra]))
    natural = natural_cast(ld, canon_rows)
    present: set[str] = set()
    added: list[str] = []
    for shot in ld.shots:
        edits = PersonEdits.of(shot)
        present |= (natural[str(shot["id"])] | set(edits.cast.add)) - set(edits.cast.remove)
        added += edits.cast.add
    kept = [cid for cid in dict.fromkeys([*base, *added]) if cid in present]
    removed = {r for shot in ld.shots for r in PersonEdits.of(shot).cast.remove}
    return [*kept, *(i for i in dict.fromkeys(extra) if i not in kept and i not in removed)]


async def view(repos: Repos, access: ProductionAccess, scene_id: UUID) -> SceneView:
    production_id = access.production_id
    ld, canon_rows, packet_row = await asyncio.gather(load(repos, access, scene_id), repos.canon.list(production_id),
                                                      repos.packets.get(production_id, scene_id))
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
    summary_of = {str(c.get("slate")): str(c.get("summary") or "")
                  for c in ((_raphael_result(scene) or {}).get("clips") or []) if isinstance(c, dict)}
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
            planner=str(row.get("planner") or "classic"),
            slate=str(row.get("slate") or ""), role=str(row.get("role") or ""),
            priority=str(row.get("priority") or ""), stage=int(row.get("stage") or 0),
            anchor=[str(a) for a in row.get("anchor") or []], blend=str(row.get("blend") or ""),
            summary=summary_of.get(str(row.get("slate") or ""), ""),
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
    for cid in scene_canon_ids(ld, canon_rows, briefed_ids(packet_row, scene)):
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
        staging_findings=staging_findings(staging, kernel_items, result, cast_names, shot_of_number),
        read_from=scene.get("read_from"), read_confirmed_at=scene.get("read_confirmed_at"))


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


# ── Shot Planner Adam (plan/2026-11-04b) ────────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/adam", response_model=AdamView, response_model_by_alias=True)
async def get_adam(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> AdamView:
    """The scene's Adam plan: the analysis, the treatment in use and the two others, the moments (script, implied,
    added by the director), the cards, the sound map, what code and the critics said, and what the scene had before."""
    ld = await load(repos, access, scene_id)
    stored = _adam_plan(ld.scene)
    made_by_adam = any(s.get("planner") == "adam" for s in ld.shots)
    return AdamView(scene_id=scene_id, planner="adam" if made_by_adam else "classic",
                    plan=stored if made_by_adam else None)


def _adam_plan(scene: Row) -> dict[str, Any] | None:
    """The scene's stored Adam plan, or None when Adam never planned it."""
    raw = scene.get("adam")
    return raw if isinstance(raw, dict) and raw.get("planner") == "adam" else None


async def _adam_job(repos: Repos, access: ProductionAccess, scene_id: UUID, state: dict[str, Any],
                    action: str) -> ResplitStarted:
    job_id = await task_manager.dispatch(JobKind.PLAN_SCENE_ADAM, repos, actor_user_id=access.user.id,
                                         production_id=access.production_id, request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], **state})
    await repos.audit.record(action=action, entity="scene", entity_id=str(scene_id), actor_user_id=access.user.id,
                             production_id=access.production_id, diff={"job_id": str(job_id)})
    return ResplitStarted(job_id=job_id)


@router.post("/scenes/{scene_id}/adam/plan", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def plan_with_adam(production_id: UUID, scene_id: UUID, body: AdamPlanRequest, access: CanDirect,
                         repos: ReposDep) -> ResplitStarted:
    """Plan the scene's shots with Shot Planner Adam ("Plan with Adam"), or, with a treatment, plan its cards again
    under another one. Replaces the shot list; an approved scene is refused."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    if not ld.scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    # "Plan with Adam" is a person asking to plan again: it never reuses an unchanged plan (plan/2026-11-05 L5).
    return await _adam_job(repos, access, scene_id, {"edit": {"treatment": body.treatment} if body.treatment else {},
                                                     "screening": body.screening, "replan": True}, "scene.adam_plan")


@router.post("/scenes/{scene_id}/adam/moments/{moment_id}/remove", response_model=ResplitStarted,
             status_code=status.HTTP_202_ACCEPTED)
async def remove_adam_moment(production_id: UUID, scene_id: UUID, moment_id: str, access: CanDirect,
                             repos: ReposDep) -> ResplitStarted:
    """Take out something the director added ("Added by director"). The moment and any card left with nothing go, and
    the same addition is never added back when the scene is planned again. A moment that presents the script cannot be
    removed. No model is called."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    stored = _adam_plan(ld.scene)
    if stored is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene was not planned by Shot Planner Adam.")
    found = next((m for m in stored.get("moments") or [] if m.get("id") == moment_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The plan has no such moment.")
    if found.get("tier") == "script":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "A moment that presents the script cannot be removed.")
    return await _adam_job(repos, access, scene_id, {"edit": {"remove_moment": moment_id}}, "scene.adam_remove_moment")


# ── Shot Planner David (plan/2026-11-05e) ───────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/david", response_model=DavidView, response_model_by_alias=True)
async def get_david(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> DavidView:
    """The scene's David plan: the author's notes, the shots with their camera, what was added, the checks (what code
    mended, what a repair changed, what is reported), the end state, the look changes and the joins with the scenes
    around it."""
    ld = await load(repos, access, scene_id)
    stored = _david_plan(ld.scene)
    made_by_david = any(s.get("planner") == "david" for s in ld.shots)
    return DavidView(scene_id=scene_id, planner="david" if made_by_david else "classic",
                     plan=stored if made_by_david else None)


def _david_plan(scene: Row) -> dict[str, Any] | None:
    """The scene's stored David plan, or None when David never planned it."""
    raw = scene.get("david")
    return raw if isinstance(raw, dict) and raw.get("planner") == "david" else None


async def _david_job(repos: Repos, access: ProductionAccess, scene_id: UUID, state: dict[str, Any],
                     action: str) -> ResplitStarted:
    job_id = await task_manager.dispatch(JobKind.PLAN_SCENE_DAVID, repos, actor_user_id=access.user.id,
                                         production_id=access.production_id, request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], **state})
    await repos.audit.record(action=action, entity="scene", entity_id=str(scene_id), actor_user_id=access.user.id,
                             production_id=access.production_id, diff={"job_id": str(job_id)})
    return ResplitStarted(job_id=job_id)


@router.post("/scenes/{scene_id}/david/plan", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def plan_with_david(production_id: UUID, scene_id: UUID, body: DavidPlanRequest, access: CanDirect,
                          repos: ReposDep) -> ResplitStarted:
    """Plan the scene's shots with Shot Planner David ("Plan with David"), or, with a note, change the plan David made.
    Replaces the shot list; an approved scene is refused. The scenes after it that carry on from it and that David
    planned are planned again in order until one's end state comes out the same."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    if not ld.scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    note = body.note.strip()
    if note and _david_plan(ld.scene) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene was not planned by Shot Planner David, so there is "
                                                     "no plan to change. Plan it with David first.")
    # "Plan with David" is a person asking to plan again: it never reuses an unchanged plan (plan §4.4).
    return await _david_job(repos, access, scene_id, {"edit": {"note": note} if note else {}, "replan": True},
                            "scene.david_plan")


@router.post("/scenes/{scene_id}/david/added/{number}/remove", response_model=ResplitStarted,
             status_code=status.HTTP_202_ACCEPTED)
async def remove_david_addition(production_id: UUID, scene_id: UUID, number: int, access: CanDirect,
                                repos: ReposDep) -> ResplitStarted:
    """Take out something David added (addition `number`, counted from 1 in the plan's `added`). The shot that exists
    for
    it goes, and the same addition is never added back when the scene is planned again. A shot that shows the script
    cannot
    be removed this way. No model is called."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    stored = _david_plan(ld.scene)
    if stored is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene was not planned by Shot Planner David.")
    plan = stored.get("plan") or {}
    added = plan.get("added") or []
    if not 1 <= number <= len(added):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The plan has no such addition.")
    shot = next((s for s in plan.get("shots") or [] if s.get("n") == added[number - 1].get("shot")), None)
    if shot is not None and (shot.get("blocks") or shot.get("lines")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "That addition is part of a shot that shows the script. Plan again with a note.")
    return await _david_job(repos, access, scene_id, {"edit": {"remove_added": number}}, "scene.david_remove_added")


# ── Shot Planner Jonathan (plan/2026-11-06b) ───────────────────────────────────────────────────


@router.get("/scenes/{scene_id}/jonathan", response_model=JonathanView, response_model_by_alias=True)
async def get_jonathan(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> JonathanView:
    """The scene's Jonathan plan: the author's notes, the shots with their camera, what was added, the checks (what code
    mended, what a repair changed, what is reported), the end state, the look changes and the joins with the scenes
    around it."""
    ld = await load(repos, access, scene_id)
    stored = _jonathan_plan(ld.scene)
    made_by_jonathan = any(s.get("planner") == "jonathan" for s in ld.shots)
    return JonathanView(scene_id=scene_id, planner="jonathan" if made_by_jonathan else "classic",
                     plan=stored if made_by_jonathan else None)


def _jonathan_plan(scene: Row) -> dict[str, Any] | None:
    """The scene's stored Jonathan plan, or None when Jonathan never planned it."""
    raw = scene.get("jonathan")
    return raw if isinstance(raw, dict) and raw.get("planner") == "jonathan" else None


async def _jonathan_job(repos: Repos, access: ProductionAccess, scene_id: UUID, state: dict[str, Any],
                     action: str) -> ResplitStarted:
    job_id = await task_manager.dispatch(JobKind.PLAN_SCENE_JONATHAN, repos, actor_user_id=access.user.id,
                                         production_id=access.production_id, request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], **state})
    await repos.audit.record(action=action, entity="scene", entity_id=str(scene_id), actor_user_id=access.user.id,
                             production_id=access.production_id, diff={"job_id": str(job_id)})
    return ResplitStarted(job_id=job_id)


@router.post("/scenes/{scene_id}/jonathan/plan", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def plan_with_jonathan(production_id: UUID, scene_id: UUID, body: JonathanPlanRequest, access: CanDirect,
                          repos: ReposDep) -> ResplitStarted:
    """Plan the scene's shots with Shot Planner Jonathan ("Plan with Jonathan"), or, with a note, change the plan
    Jonathan made.
    Replaces the shot list; an approved scene is refused. The scenes after it that carry on from it and that Jonathan
    planned are planned again in order until one's end state comes out the same."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    if not ld.scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    note = body.note.strip()
    if note and _jonathan_plan(ld.scene) is None:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "This scene was not planned by Shot Planner Jonathan, so there is "
                                                     "no plan to change. Plan it with Jonathan first.")
    # "Plan with Jonathan" is a person asking to plan again: it never reuses an unchanged plan (plan §4.4).
    return await _jonathan_job(repos, access, scene_id, {"edit": {"note": note} if note else {}, "replan": True},
                            "scene.jonathan_plan")


@router.post("/scenes/{scene_id}/jonathan/added/{number}/remove", response_model=ResplitStarted,
             status_code=status.HTTP_202_ACCEPTED)
async def remove_jonathan_addition(production_id: UUID, scene_id: UUID, number: int, access: CanDirect,
                                repos: ReposDep) -> ResplitStarted:
    """Take out something Jonathan added (addition `number`, counted from 1 in the plan's `added`). The shot that exists
    for
    it goes, and the same addition is never added back when the scene is planned again. A shot that shows the script
    cannot
    be removed this way. No model is called."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    stored = _jonathan_plan(ld.scene)
    if stored is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene was not planned by Shot Planner Jonathan.")
    plan = stored.get("plan") or {}
    added = plan.get("added") or []
    if not 1 <= number <= len(added):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The plan has no such addition.")
    shot = next((s for s in plan.get("shots") or [] if s.get("n") == added[number - 1].get("shot")), None)
    if shot is not None and (shot.get("blocks") or shot.get("lines")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "That addition is part of a shot that shows the script. Plan again with a note.")
    return await _jonathan_job(repos, access, scene_id, {"edit": {"remove_added": number}},
        "scene.jonathan_remove_added")


# ── Shot Planner Raphael (plan/2026-11-08e) ────────────────────────────────────────────────────

RAPHAEL_CAPS = (1, 1.5, 2, 2.5, 3)


def _raphael_result(scene: Row) -> dict[str, Any] | None:
    """The scene's stored Raphael result, or None when Raphael never planned it."""
    raw = scene.get("raphael")
    return raw if isinstance(raw, dict) and raw.get("planner") == "raphael" else None


def _a_cap(cap: float | None) -> float | None:
    if cap is not None and cap not in RAPHAEL_CAPS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "The length cap is one of 1.5, 2, 2.5 or 3 times the scene's length.")
    return cap


@router.get("/scenes/{scene_id}/raphael", response_model=RaphaelView, response_model_by_alias=True)
async def get_raphael(production_id: UUID, scene_id: UUID, access: CanView, repos: ReposDep) -> RaphaelView:
    """The scene's Raphael result: the intended cut, the shoot bin by moment with its slates (the must clips and the
    cinematic clips under their anchors), the editor and blend notes, the moment review, what is left reported, the
    length cap used and the seconds against the target and the cap. Never a cost."""
    ld = await load(repos, access, scene_id)
    stored = _raphael_result(ld.scene)
    made_by_raphael = any(s.get("planner") == "raphael" for s in ld.shots)
    states: dict[str, ShotStateView] = {}
    for shot in ld.shots if made_by_raphael else []:
        intent = ShotIntent.of(shot)
        if intent is not None and (intent.story or intent.opens or intent.ends) and shot.get("slate"):
            states[str(shot["slate"])] = ShotStateView(story=intent.story, opens=intent.opens, ends=intent.ends)
    faults = [r for r in (stored or {}).get("left") or [] if isinstance(r, dict) and r.get("code") == "state"]
    return RaphaelView(scene_id=scene_id, planner="raphael" if made_by_raphael else "classic",
                       result=stored if made_by_raphael else None,
                       default_cap=float(ld.settings.raphael_length_cap),
                       states=states, state_faults=faults if made_by_raphael else [])


async def _raphael_job(repos: Repos, access: ProductionAccess, scene_id: UUID, kind: JobKind, state: dict[str, Any],
                       action: str) -> ResplitStarted:
    job_id = await task_manager.dispatch(kind, repos, actor_user_id=access.user.id, production_id=access.production_id,
                                         request={"scene_id": str(scene_id)},
                                         state={"scene_ids": [str(scene_id)], **state})
    await repos.audit.record(action=action, entity="scene", entity_id=str(scene_id), actor_user_id=access.user.id,
                             production_id=access.production_id, diff={"job_id": str(job_id)})
    return ResplitStarted(job_id=job_id)


@router.post("/scenes/{scene_id}/raphael/plan", response_model=ResplitStarted, status_code=status.HTTP_202_ACCEPTED)
async def plan_with_raphael(production_id: UUID, scene_id: UUID, body: RaphaelPlanRequest, access: CanDirect,
                            repos: ReposDep) -> ResplitStarted:
    """Plan the scene with Shot Planner Raphael ("Plan with Raphael"): the must bin, then the cinematic pass, under the
    length cap asked for (else the production's). Replaces the shot list; an approved scene is refused."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    if not ld.scene.get("script"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene has no script to plan shots from.")
    edit: dict[str, Any] = {}
    if (cap := _a_cap(body.cap)) is not None:
        edit["cap"] = cap
    if note := body.note.strip():
        edit["note"] = note
    # "Plan with Raphael" is a person asking to plan again: it never reuses an unchanged result.
    return await _raphael_job(repos, access, scene_id, JobKind.PLAN_SCENE_RAPHAEL, {"edit": edit, "replan": True},
                              "scene.raphael_plan")


@router.post("/scenes/{scene_id}/raphael/cinematic", response_model=ResplitStarted,
             status_code=status.HTTP_202_ACCEPTED)
async def more_cinematic(production_id: UUID, scene_id: UUID, body: RaphaelCinematicRequest, access: CanDirect,
                         repos: ReposDep) -> ResplitStarted:
    """"More cinematic": run the cinematic pass again over the scene's must bin, with the length cap asked for. The must
    clips stay as they are; the cinematic clips are written again. Needs a scene Raphael planned with a finished
    stage 1."""
    ld = await load(repos, access, scene_id)
    _editable(ld.scene)
    stored = _raphael_result(ld.scene)
    if stored is None or stored.get("stage1") != "finished":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Raphael has not finished the must clips for this scene, so there is nothing to add to. "
                            "Plan it with Raphael first.")
    edit: dict[str, Any] = {"stage": "cinematic"}
    if (cap := _a_cap(body.cap)) is not None:
        edit["cap"] = cap
    return await _raphael_job(repos, access, scene_id, JobKind.CINEMATIC_SCENE_RAPHAEL, {"edit": edit},
                              "scene.raphael_cinematic")


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


@router.post("/scenes/{scene_id}/read-check", response_model=SceneView)
async def confirm_read(production_id: UUID, scene_id: UUID, access: CanWrite, repos: ReposDep) -> SceneView:
    """A person checked the dialogue of a scene the document reader read from page images against the page
    (plan/2026-11-06f decision 6). Only a "pages" scene has anything to confirm; the next build that rewrites the scene
    clears it."""
    ld = await load(repos, access, scene_id)
    if ld.scene.get("read_from") != "pages":
        raise HTTPException(status.HTTP_409_CONFLICT, "This scene was not read from page images.")
    if not ld.scene.get("read_confirmed_at"):
        await repos.scenes.update(scene_id, {"read_confirmed_by": str(access.user.id),
                                             "read_confirmed_at": datetime.now(UTC).isoformat()})
        await repos.audit.record(action="scene.read_check", entity="scene", entity_id=str(scene_id),
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
