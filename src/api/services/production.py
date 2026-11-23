"""The Production panel's rules that are not routes (PLAN.md §6.1, §13 step 19).

* STALENESS is computed on every read from what each design, frame and prompt was made against
  (`contracts.producer.Pins`) and what the shot, its script and its canon cards are now. Nothing
  is redone automatically: the panel shows what is out of date and why, and a person decides.
  plan/2026-11-20d D8: the camera too. A frame is out of date when the camera's PICTURE moved (size,
  angle, height, lens, stop, focus, composition, side of the line, lighting, the opening picture) or
  the shot prompt it was drawn from was rewritten; a video prompt when the picture or the MOTION moved;
  the shot prompt (`design.shot_prompt`) when either moved, or the script, the cast or the looks did.
* The PROMPT LOCK: a shot that opens on a generated frame gets a prompt only once one of its
  frames is accepted and that frame still matches the shot; a shot that carries on from the
  previous take opens on that take's last frame and needs none.
* The SCENE LOCK (approval) means the picture work is done: designs, camera and frames are made while the
  scene is NOT approved. Video prompts and videos are made whether it is approved or not.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from contracts import board as board_kit
from contracts import picture_pins, sceneplan
from contracts.frame_brief import agent_camera
from contracts.producer import (
    CameraCheck,
    CameraSettings,
    CastMember,
    FrameStage,
    PersonEdits,
    Pins,
    apply_waivers,
    default_camera,
    frame_stage,
    look_pins,
    pins_for,
    script_hash,
    shot_canon_ids,
    shot_items,
    stale_reasons,
)
from contracts.shotplan import Item
from contracts.staging import ShotIntent, Staging, coverage_checks, intent_basis, shot_cast, staging, staging_checks
from contracts.veo import FrameStrategy

Row = dict[str, Any]
LOCKED = "This scene is approved and locked. Unapprove it to make or change frames."
NO_SHOT_PROMPT = "no shot prompt"


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""), appearance=str(card.get("appearance") or ""),
                      gender=str(card.get("gender") or ""))


@dataclass
class ShotState:
    """One shot as the panel sees it now."""

    row: Row
    items: list[Item]
    cast: list[CastMember]
    pins: Pins
    recommended: CameraSettings
    camera: CameraSettings
    design_reasons: list[str] = field(default_factory=list)  # [] = current; ["no design"] = none
    frames: list[Row] = field(default_factory=list)  # the FINAL first frames (uploads and carried frames too)
    drafts: list[Row] = field(default_factory=list)  # low-quality drafts: only ever a reference for a final
    frame_reasons: dict[str, list[str]] = field(default_factory=dict)  # for drafts too
    accepted: Row | None = None  # the accepted FINAL: it opens the video prompt
    accepted_draft: Row | None = None  # the accepted draft: what a final may be painted from
    prompt: Row | None = None
    prompt_reasons: list[str] = field(default_factory=list)
    lock: str = ""  # why a prompt cannot be made now; "" = unlocked
    canon_refs: list[str] = field(default_factory=list)  # "C01 v2", "L01 v1": the cards pinned now
    edits: PersonEdits = field(default_factory=PersonEdits)  # what a person set on the shot by hand
    staged: Staging = field(default_factory=Staging)  # who the camera sees, who is only heard
    intent: ShotIntent | None = None
    intent_stale: bool = False  # written against other material (a person's intent is kept anyway)
    shot_prompt: Row | None = None  # plan/2026-11-20d: the Shot prompt agent's stored first frame + video
    shot_prompt_reasons: list[str] = field(default_factory=list)  # [] = current; [NO_SHOT_PROMPT] = none

    @property
    def shot_prompt_current(self) -> Row | None:
        """The stored shot prompt while it still fits the shot (D5): its frame words paint the next frame."""
        return self.shot_prompt if self.shot_prompt and not self.shot_prompt_reasons else None

    @property
    def seen(self) -> list[CastMember]:
        return [c for c in self.cast if c.id in self.staged.on_screen]

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def code(self) -> str:
        return f"S{int(self.row['number']):02d}"

    @property
    def has_design(self) -> bool:
        return bool((self.row.get("design") or {}).get("pins")) and bool(self.row.get("ir"))


def scene_states(scene: Row, shots: list[Row], lines: list[Row], canon: list[Row], frames: list[Row],
                 prompts: dict[str, Row], looks: Mapping[str, Mapping[str, Any]] | None = None,
                 board: Sequence[Row] = ()) -> list[ShotState]:
    """`looks`: character id → the look the scene uses now (`contracts.canon.looks_in_force`). A
    frame painted with another look, or before its look changed, is out of date. `board`: the scene's Scene board
    rows: a shot prompt written before its approved panel is out of date (plan/2026-11-23d D2)."""
    items = sceneplan.scene_items(scene, lines)
    characters = [c for c in canon if c["kind"] == "character"]
    members = {str(c["id"]): cast_member(c) for c in canon}
    versions = {k: m.version for k, m in members.items()}
    out: list[ShotState] = []
    for shot in sorted(shots, key=lambda s: int(s["number"])):
        own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
        edits = PersonEdits.of(shot)
        cast_ids = shot_cast(own, characters, shot)
        version = int(shot.get("version") or 1)
        pins = pins_for(shot_version=version, scene=scene, items=own, cast_ids=cast_ids, versions=versions,
                        edits=edits)
        design = shot.get("design") or {}
        default = default_camera(str(shot.get("framing") or "MS"), heading=str(scene.get("heading") or ""),
                                 time_of_day=str(scene.get("time_of_day") or ""))
        try:
            recommended = CameraSettings.model_validate(design["recommended"]) if design.get("recommended") else default
        except ValueError:
            recommended = default
        st = ShotState(row=shot, items=own, cast=[members[c] for c in cast_ids], pins=pins, recommended=recommended,
                       camera=recommended.with_overrides(shot.get("camera_overrides") or {}), edits=edits,
                       staged=staging(own, characters, shot, cast_ids=cast_ids), intent=ShotIntent.of(shot))
        if st.intent is not None:
            st.intent_stale = st.intent.stale(intent_basis(version, script_hash(scene, own)))

        worn = look_pins(shot_canon_ids(scene, cast_ids, edits), looks or {})
        block = agent_camera(shot)
        motion_now = picture_pins.motion(st.camera, recommended, block, edits.video_note)

        def reasons(made: Any, st: ShotState = st, version: int = version, frame: bool = False,
                    worn: Any = worn, picture: Any = None, motion: Any = None, block: Any = block) -> list[str]:
            if not made:
                return []
            out_ = stale_reasons(made, shot_version=version, script_hash=st.pins.script_hash, canon=members,
                                 looks=worn if frame else None, picture=picture, motion=motion,
                                 designed=bool(block))
            if set(Pins.model_validate(made).canon) != set(st.pins.canon) and not out_:
                out_.append("Different people or place in the shot.")
            return out_

        record = design.get("shot_prompt")
        if isinstance(record, dict) and record.get("frame") and record.get("pins"):
            st.shot_prompt = record
            st.shot_prompt_reasons = reasons(record["pins"], frame=True,
                                             picture=picture_pins.picture(st.camera, block), motion=motion_now)
            changed = board_kit.board_reason(record, board, shot)  # the same rule the frame_compose world keeps
            if changed:
                st.shot_prompt_reasons.append(changed)
        else:
            st.shot_prompt_reasons = [NO_SHOT_PROMPT]
        # a frame drawn from the shot prompt pinned its opening: a rewritten one marks the frame (D8)
        picture_now = picture_pins.picture(st.camera, block,
                                           picture_pins.opening_text((st.shot_prompt or {}).get("opening")))

        st.canon_refs = [f"{members[c].code} v{v}" for c, v in pins.canon.items() if c in members]
        st.design_reasons = reasons(design.get("pins")) if st.has_design else ["no design"]
        if st.has_design and st.intent is not None and design.get("intent") \
                and design["intent"] != st.intent.stamp():
            st.design_reasons.append("What the shot is for changed.")
        own_frames = [f for f in frames if str(f["shot_id"]) == st.id]
        st.frames = [f for f in own_frames if frame_stage(f) == FrameStage.FINAL]
        st.drafts = [f for f in own_frames if frame_stage(f) == FrameStage.DRAFT]
        st.frame_reasons = {str(f["id"]): reasons(f.get("pins"), frame=True, picture=picture_now)
                            for f in own_frames}
        st.accepted = next((f for f in st.frames if f.get("accepted_at")), None)
        st.accepted_draft = next((f for f in st.drafts if f.get("accepted_at")), None)
        st.prompt = prompts.get(st.id)
        if st.prompt:
            pinned = (st.prompt.get("pins") or {}) if isinstance(st.prompt.get("pins"), dict) else {}
            st.prompt_reasons = reasons(st.prompt.get("pins"), picture=picture_pins.picture(st.camera, block),
                                        motion=motion_now)
            carried = shot.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME
            if not carried and str(st.prompt.get("frame_id") or "") != str((st.accepted or {}).get("id") or ""):
                st.prompt_reasons.append("A different first frame is accepted now.")
            if not pinned.get("motion") and not block and (st.prompt.get("camera") or {}) and \
                    st.prompt.get("camera") != st.camera.model_dump():  # a prompt made before D8
                st.prompt_reasons.append("The camera settings changed.")
        st.lock = _lock(st)
        out.append(st)
    return out


def _lock(st: ShotState) -> str:
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        return ""
    if st.accepted is None:
        return "Accept a first frame to unlock the prompt."
    if st.frame_reasons.get(str(st.accepted["id"])):
        return "The accepted frame no longer matches the shot. Make and accept a new one."
    return ""


def camera_checks(states: list[ShotState]) -> dict[str, list[CameraCheck]]:
    """The camera card's free checks, from the camera as it stands across the whole scene: the
    camera's own, who is seen or heard (`contracts.staging`), and the scene's variety of setups."""
    from contracts.producer import camera_checks as checks_for

    cameras = [s.camera for s in states]
    coverage = coverage_checks([str(s.row.get("framing") or "MS") for s in states], cameras,
                               [s.code for s in states])
    out: dict[str, list[CameraCheck]] = {}
    for i, st in enumerate(states):
        sound_mode = str(st.row.get("sound_mode") or "ambient")
        speakers = list(dict.fromkeys(x.speaker_id for x in st.items if x.is_line and x.speaker_id))
        raw_on = (st.row.get("design") or {}).get("on_screen")
        staged = staging_checks(staged=st.staged, names={c.id: c.name for c in st.cast}, sound_mode=sound_mode,
                                speaker_ids=speakers, ir=st.row.get("ir") or {},
                                design_on_screen=[str(x) for x in raw_on] if isinstance(raw_on, list) else None,
                                intent=st.intent, items=st.items,
                                framing=str(st.row.get("framing") or "MS")) if st.has_design else []
        checks = checks_for(index=i, cameras=cameras, framing=str(st.row.get("framing") or "MS"),
                            sound_mode=sound_mode, cast=st.seen,
                            speaker_ids=list(dict.fromkeys(x.speaker_id for x in st.items
                                                           if x.is_line and x.speaker_id)),
                            frame_strategy=str(st.row.get("frame_strategy") or "generate"),
                            first_code=states[0].code, previous_code=states[i - 1].code if i else "")
        checks = [*checks, *staged, *coverage[i]]
        out[st.id] = apply_waivers(checks, st.edits.waived_checks)  # advisories a person chose to ignore
    return out
