"""The Production panel's rules that are not routes (PLAN.md §6.1, §13 step 19).

* STALENESS is computed on every read from what each design, frame and prompt was made against
  (`contracts.producer.Pins`) and what the shot, its script and its canon cards are now. Nothing
  is redone automatically: the panel shows what is out of date and why, and a person decides.
* The PROMPT LOCK: a shot that opens on a generated frame gets a prompt only once one of its
  frames is accepted and that frame still matches the shot; a shot that carries on from the
  previous take opens on that take's last frame and needs none. Production work starts when the
  director has approved the scene (it is locked from then on).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts import sceneplan
from contracts.producer import (
    CameraCheck,
    CameraSettings,
    CastMember,
    PersonEdits,
    Pins,
    apply_waivers,
    cast_in,
    default_camera,
    pins_for,
    shot_items,
    stale_reasons,
)
from contracts.production import SceneStatus
from contracts.shotplan import Item
from contracts.veo import FrameStrategy

Row = dict[str, Any]
NOT_APPROVED = "Approve this scene in the Director panel first."


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
    frames: list[Row] = field(default_factory=list)
    frame_reasons: dict[str, list[str]] = field(default_factory=dict)
    accepted: Row | None = None
    prompt: Row | None = None
    prompt_reasons: list[str] = field(default_factory=list)
    lock: str = ""  # why a prompt cannot be made now; "" = unlocked
    canon_refs: list[str] = field(default_factory=list)  # "C01 v2", "L01 v1": the cards pinned now
    edits: PersonEdits = field(default_factory=PersonEdits)  # what a person set on the shot by hand

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
                 prompts: dict[str, Row]) -> list[ShotState]:
    items = sceneplan.items_for(scene.get("script") or [], lines)
    characters = [c for c in canon if c["kind"] == "character"]
    members = {str(c["id"]): cast_member(c) for c in canon}
    versions = {k: m.version for k, m in members.items()}
    approved = scene.get("status") == SceneStatus.APPROVED
    out: list[ShotState] = []
    for shot in sorted(shots, key=lambda s: int(s["number"])):
        own = shot_items(items, int(shot["block_start"]), int(shot["block_end"]))
        edits = PersonEdits.of(shot)
        cast_ids = cast_in(own, characters, edits)
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
                       camera=recommended.with_overrides(shot.get("camera_overrides") or {}), edits=edits)

        def reasons(made: Any, st: ShotState = st, version: int = version) -> list[str]:
            if not made:
                return []
            out_ = stale_reasons(made, shot_version=version, script_hash=st.pins.script_hash, canon=members)
            if set(Pins.model_validate(made).canon) != set(st.pins.canon) and not out_:
                out_.append("Different people or place in the shot.")
            return out_

        st.canon_refs = [f"{members[c].code} v{v}" for c, v in pins.canon.items() if c in members]
        st.design_reasons = reasons(design.get("pins")) if st.has_design else ["no design"]
        st.frames = [f for f in frames if str(f["shot_id"]) == st.id]
        st.frame_reasons = {str(f["id"]): reasons(f.get("pins")) for f in st.frames}
        st.accepted = next((f for f in st.frames if f.get("accepted_at")), None)
        st.prompt = prompts.get(st.id)
        if st.prompt:
            st.prompt_reasons = reasons(st.prompt.get("pins"))
            carried = shot.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME
            if not carried and str(st.prompt.get("frame_id") or "") != str((st.accepted or {}).get("id") or ""):
                st.prompt_reasons.append("A different first frame is accepted now.")
            if (st.prompt.get("camera") or {}) and st.prompt.get("camera") != st.camera.model_dump():
                st.prompt_reasons.append("The camera settings changed.")
        st.lock = _lock(st, approved)
        out.append(st)
    return out


def _lock(st: ShotState, approved: bool) -> str:
    if not approved:
        return NOT_APPROVED
    if st.row.get("frame_strategy") == FrameStrategy.CARRY_LAST_FRAME:
        return ""
    if st.accepted is None:
        return "Accept a first frame to unlock the prompt."
    if st.frame_reasons.get(str(st.accepted["id"])):
        return "The accepted frame no longer matches the shot. Make and accept a new one."
    return ""


def camera_checks(states: list[ShotState]) -> dict[str, list[CameraCheck]]:
    """The camera card's free checks, from the camera as it stands across the whole scene."""
    from contracts.producer import camera_checks as checks_for

    cameras = [s.camera for s in states]
    out: dict[str, list[CameraCheck]] = {}
    for i, st in enumerate(states):
        checks = checks_for(index=i, cameras=cameras, framing=str(st.row.get("framing") or "MS"),
                            sound_mode=str(st.row.get("sound_mode") or "ambient"), cast=st.cast,
                            speaker_ids=list(dict.fromkeys(x.speaker_id for x in st.items
                                                           if x.is_line and x.speaker_id)),
                            frame_strategy=str(st.row.get("frame_strategy") or "generate"),
                            first_code=states[0].code, previous_code=states[i - 1].code if i else "")
        out[st.id] = apply_waivers(checks, st.edits.waived_checks)  # advisories a person chose to ignore
    return out
