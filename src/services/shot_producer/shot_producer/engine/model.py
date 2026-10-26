"""What the producer works on, built once per scene from stored rows.

Upstream's engine reads a Nova `ProductionTreatment`; Hiru's equivalent is already in the
database: the approved script, the director's shot list (Phase 3) and the canon. These are
plain dataclasses so the engine never touches a row shape twice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts import sceneplan
from contracts.producer import (
    CameraSettings,
    CastMember,
    Pins,
    cast_in,
    default_camera,
    pins_for,
    shot_items,
    stale_reasons,
)
from contracts.production import ProductionSettings
from contracts.shotplan import Item
from contracts.veo import ASPECT_RATIO, Orientation

Row = dict[str, Any]


@dataclass
class Line:
    id: str
    speaker: str
    character_id: str | None
    text: str  # verbatim from the approved script (Sinhala)
    delivery: str
    beat_index: int | None


@dataclass
class ShotInput:
    id: str
    number: int
    title: str
    framing: str  # the director's size: WIDE | MS | MCU | CU | TWO | OTS | INSERT
    duration_s: int
    sound_mode: str
    camera_link: str
    frame_strategy: str
    beats: list[tuple[int, int]]
    beat_notes: list[Row]  # the director's notes per beat (camera, director_line, action)
    items: list[Item]  # the script blocks this shot plays
    lines: list[Line]
    cast: list[CastMember]  # characters in the shot, canon order
    words: int
    word_target: int
    version: int
    row: Row  # the stored shot (design, ir, camera_overrides ...)
    pins: Pins

    @property
    def code(self) -> str:
        return f"S{self.number:02d}"

    @property
    def speaker_ids(self) -> list[str]:
        return list(dict.fromkeys(ln.character_id for ln in self.lines if ln.character_id))

    def stored_design(self) -> Row:
        return dict(self.row.get("design") or {})

    def recommended(self, scene: SceneInput) -> CameraSettings:
        rec = self.stored_design().get("recommended")
        if rec:
            try:
                return CameraSettings.model_validate(rec)
            except ValueError:
                pass
        return default_camera(self.framing, heading=scene.heading, time_of_day=scene.time_of_day)

    def camera(self, scene: SceneInput) -> CameraSettings:
        """The camera as it stands: the recommendation and a person's changes."""
        return self.recommended(scene).with_overrides(self.row.get("camera_overrides") or {})


@dataclass
class SceneInput:
    id: str
    number: int
    episode_number: int
    heading: str
    time_of_day: str
    location: CastMember | None
    location_look: str
    shots: list[ShotInput] = field(default_factory=list)


@dataclass
class ProductionInput:
    id: str
    title: str
    aspect_ratio: str
    settings: ProductionSettings
    cast: list[CastMember]  # every character, canon order
    by_id: dict[str, CastMember]  # every entity
    style_note: str = ""
    charter: str = ""
    techniques: str = ""


def cast_member(row: Row) -> CastMember:
    current = row.get("current") or {}
    card = current.get("card") or {}
    return CastMember(id=str(row["id"]), code=str(row["code"]), name=str(row["name"]), kind=str(row["kind"]),
                      version=current.get("version"), wardrobe_anchor=str(current.get("wardrobe_anchor") or ""),
                      voice_pin=str(current.get("voice_pin") or ""),
                      appearance=str(card.get("appearance") or ""), gender=str(card.get("gender") or ""))


def production_input(row: Row, canon: list[Row], persona: Row | None) -> ProductionInput:
    members = [cast_member(c) for c in canon]
    orientation = Orientation(row.get("orientation") or "horizontal")
    return ProductionInput(id=str(row["id"]), title=str(row.get("title") or ""),
                           aspect_ratio=ASPECT_RATIO[orientation],
                           settings=ProductionSettings.model_validate(row.get("settings") or {}),
                           cast=[m for m in members if m.kind == "character"], by_id={m.id: m for m in members},
                           style_note=str((persona or {}).get("style_note") or ""),
                           charter=str((persona or {}).get("charter") or ""))


def scene_input(scene: Row, shots: list[Row], lines: list[Row], canon: list[Row], prod: ProductionInput) -> SceneInput:
    """The scene with each shot's own blocks, lines, cast and current pins."""
    items = sceneplan.items_for(scene.get("script") or [], lines)
    characters = [c for c in canon if c["kind"] == "character"]
    versions = {m.id: m.version for m in prod.by_id.values()}
    by_line = {str(ln["id"]): ln for ln in lines}
    location = prod.by_id.get(str(scene.get("location_id"))) if scene.get("location_id") else None
    loc_row = next((c for c in canon if location and str(c["id"]) == location.id), None)
    look = str(((loc_row or {}).get("current") or {}).get("card", {}).get("look") or "") if loc_row else ""
    out = SceneInput(id=str(scene["id"]), number=int(scene["number"]),
                     episode_number=int((scene.get("episode") or {}).get("number") or 0),
                     heading=str(scene.get("heading") or ""), time_of_day=str(scene.get("time_of_day") or ""),
                     location=location, location_look=look)
    for s in shots:
        own = shot_items(items, int(s["block_start"]), int(s["block_end"]))
        cast_ids = cast_in(own, characters)
        shot_lines = [Line(id=i.line_id or "", speaker=i.speaker, character_id=i.speaker_id, text=i.text,
                           delivery=i.delivery,
                           beat_index=(by_line.get(i.line_id or "") or {}).get("beat_index"))
                      for i in own if i.is_line]
        out.shots.append(ShotInput(
            id=str(s["id"]), number=int(s["number"]), title=str(s.get("title") or ""),
            framing=str(s.get("framing") or "MS"), duration_s=int(s["duration_s"]),
            sound_mode=str(s.get("sound_mode") or "ambient"), camera_link=str(s.get("camera_link") or "cut"),
            frame_strategy=str(s.get("frame_strategy") or "generate"),
            beats=[(int(b["start_s"]), int(b["end_s"])) for b in s.get("beats") or []],
            beat_notes=[{k: str(b.get(k) or "") for k in sceneplan.BEAT_TEXT} for b in s.get("beats") or []],
            items=own, lines=shot_lines, cast=[prod.by_id[c] for c in cast_ids if c in prod.by_id],
            words=int(s.get("words") or 0), word_target=int(s.get("word_target") or 0),
            version=int(s.get("version") or 1), row=s,
            pins=pins_for(shot_version=int(s.get("version") or 1), scene=scene, items=own, cast_ids=cast_ids,
                          versions=versions)))
    return out


def design_stale(shot: ShotInput, prod: ProductionInput) -> list[str]:
    """Why the stored design no longer fits the shot; ["no design"] when there is none."""
    design = shot.stored_design()
    if not design.get("pins") or not shot.row.get("ir"):
        return ["no design"]
    reasons = stale_reasons(design["pins"], shot_version=shot.version, script_hash=shot.pins.script_hash,
                            canon=prod.by_id)
    if set(Pins.model_validate(design["pins"]).canon) != set(shot.pins.canon):
        reasons.append("Different people or place in the shot.")
    return reasons
