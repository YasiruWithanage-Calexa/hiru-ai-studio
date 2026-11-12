"""What the producer works on, built once per scene from stored rows.

Upstream's engine reads a Nova `ProductionTreatment`; Hiru's equivalent is already in the
database: the approved script, the director's shot list (Phase 3) and the canon. These are
plain dataclasses so the engine never touches a row shape twice.
"""
from __future__ import annotations

# Ported from services/shot_producer/shot_producer/engine/model.py (plan/2026-11-03 Phase 2).
from dataclasses import dataclass, field
from typing import Any

from contracts import reading as scene_reading
from contracts import sceneplan, stagemap
from contracts.holding import hands_for
from contracts.producer import (
    CameraSettings,
    CastMember,
    PersonEdits,
    Pins,
    default_camera,
    pins_for,
    script_hash,
    shot_items,
    stale_reasons,
)
from contracts.production import ProductionSettings
from contracts.shotplan import Item
from contracts.staging import AUTHORED, ScenePlan, ShotIntent, Staging, intent_basis, shot_cast, staging
from contracts.veo import ASPECT_RATIO, Orientation
from hiru_ai.core import parts

Row = dict[str, Any]
_feeling = parts.step("feeling")
Feeling: Any = _feeling.Feeling  # the feeling step's, found by id (a step does not import another step)
feeling_for = _feeling.feeling_for


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
    beat_notes: list[Row]  # the director's notes per beat (camera, director_line, action; performance from a shot card)
    items: list[Item]  # the script blocks this shot plays
    lines: list[Line]
    cast: list[CastMember]  # characters in the shot, seen or heard, canon order
    words: int
    word_target: int
    version: int
    row: Row  # the stored shot (design, ir, camera_overrides ...)
    pins: Pins
    staged: Staging = field(default_factory=Staging)  # who is seen, who is only heard
    basis: str = ""  # contracts.staging.intent_basis: what an intent must be written against
    hands: str = ""  # who holds what, and what passes between hands (contracts.holding), for the prompt
    feeling: Any = field(default_factory=Feeling)  # what the scene's reading and map ask of this shot (Phase 6)

    @property
    def code(self) -> str:
        return f"S{self.number:02d}"

    @property
    def intent(self) -> ShotIntent | None:
        return ShotIntent.of(self.row)

    @property
    def seen(self) -> list[CastMember]:
        return [c for c in self.cast if c.id in self.staged.on_screen]

    @property
    def heard(self) -> list[CastMember]:
        return [c for c in self.cast if c.id in self.staged.heard_only]

    def intent_needed(self) -> bool:
        """No intent yet, or an agent's intent written against other material. A person's own
        intent is never replaced by an agent."""
        intent = self.intent
        if intent is None:
            return True
        return intent.by not in AUTHORED and intent.stale(self.basis)

    @property
    def dop_note(self) -> str:
        """The note a person wrote for the DoP on this shot ("" when there is none)."""
        return PersonEdits.of(self.row).dop_note

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
    title: str = ""
    note: str = ""
    script_version: int = 1
    episode_title: str = ""
    synopsis: str = ""  # the episode's
    before: str = ""  # the scene before this one, in a line
    after: str = ""  # the scene after it
    row: Row = field(default_factory=dict)
    reading: scene_reading.SceneReading | None = None  # what the scene is about (plan/2026-11-01d)
    staging: stagemap.SceneStaging | None = None  # where everyone is
    items: list[Item] = field(default_factory=list)  # every block of the scene, with the reading's time on it

    @property
    def plan(self) -> ScenePlan | None:
        return ScenePlan.of(self.row)

    def plan_needed(self) -> bool:
        plan = self.plan
        return plan is None or (plan.by not in AUTHORED and plan.made_for != self.script_version)


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
    genre: str = ""  # plan/2026-11-12b: the production's genre phrase (`contracts.memory.genre_of`)


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


def scene_line(row: Row | None) -> str:
    """A neighbouring scene in one line: number, title or heading, and its first action."""
    if not row:
        return ""
    first = next((str(b.get("text") or "").strip() for b in row.get("script") or []
                  if b.get("kind") == "action" and str(b.get("text") or "").strip()), "")
    head = str(row.get("title") or row.get("heading") or "").strip()
    return " ".join(f"Scene {row.get('number')}: {head}. {first}".split())[:300]


def scene_input(scene: Row, shots: list[Row], lines: list[Row], canon: list[Row], prod: ProductionInput,
                neighbours: tuple[Row | None, Row | None] = (None, None)) -> SceneInput:
    """The scene with each shot's own blocks, lines, cast and current pins."""
    items = sceneplan.scene_items(scene, lines)
    characters = [c for c in canon if c["kind"] == "character"]
    versions = {m.id: m.version for m in prod.by_id.values()}
    by_line = {str(ln["id"]): ln for ln in lines}
    location = prod.by_id.get(str(scene.get("location_id"))) if scene.get("location_id") else None
    loc_row = next((c for c in canon if location and str(c["id"]) == location.id), None)
    look = str(((loc_row or {}).get("current") or {}).get("card", {}).get("look") or "") if loc_row else ""
    episode = scene.get("episode") or {}
    out = SceneInput(id=str(scene["id"]), number=int(scene["number"]),
                     episode_number=int(episode.get("number") or 0),
                     heading=str(scene.get("heading") or ""), time_of_day=str(scene.get("time_of_day") or ""),
                     location=location, location_look=look, title=str(scene.get("title") or ""),
                     note=str(scene.get("note") or ""), script_version=int(scene.get("script_version") or 1),
                     episode_title=str(episode.get("title") or ""),
                     synopsis=" ".join(str(episode.get("synopsis") or "").split())[:900],
                     before=scene_line(neighbours[0]), after=scene_line(neighbours[1]), row=scene,
                     reading=scene_reading.SceneReading.of(scene), staging=stagemap.SceneStaging.of(scene),
                     items=items)
    cast_names = [c.name for c in prod.cast]
    for s in shots:
        own = shot_items(items, int(s["block_start"]), int(s["block_end"]))
        edits = PersonEdits.of(s)
        cast_ids = shot_cast(own, characters, s)
        staged = staging(own, characters, s, cast_ids=cast_ids)
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
            beat_notes=[{**{k: str(b.get(k) or "") for k in sceneplan.BEAT_TEXT},
                         "performance": str(b.get("performance") or "")} for b in s.get("beats") or []],
            items=own, lines=shot_lines, cast=[prod.by_id[c] for c in cast_ids if c in prod.by_id],
            words=int(s.get("words") or 0), word_target=int(s.get("word_target") or 0),
            version=int(s.get("version") or 1), row=s,
            pins=pins_for(shot_version=int(s.get("version") or 1), scene=scene, items=own, cast_ids=cast_ids,
                          versions=versions, edits=edits),
            staged=staged,
            hands=hands_for(scene, s, [prod.by_id[c].name for c in staged.on_screen if c in prod.by_id],
                            video=True).sentence,
            basis=intent_basis(int(s.get("version") or 1), script_hash(scene, own)),
            feeling=feeling_for(out.reading, out.staging, items, own,
                                [(int(b["start_s"]), int(b["end_s"])) for b in s.get("beats") or []], cast_names)))
    return out


def restage(shot: ShotInput, scene: SceneInput, canon: list[Row], prod: ProductionInput) -> None:
    """After the shot's row changed (a new intent or design): who is in it, who is seen, and the
    pins (an intent can put a person in the shot that the script only implies)."""
    characters = [c for c in canon if c["kind"] == "character"]
    ids = shot_cast(shot.items, characters, shot.row)
    shot.cast = [prod.by_id[c] for c in ids if c in prod.by_id]
    shot.staged = staging(shot.items, characters, shot.row, cast_ids=ids)
    shot.hands = hands_for(scene.row, shot.row, [prod.by_id[c].name for c in shot.staged.on_screen
                                                 if c in prod.by_id], video=True).sentence
    shot.pins = pins_for(shot_version=shot.version, scene=scene.row, items=shot.items, cast_ids=ids,
                         versions={m.id: m.version for m in prod.by_id.values()}, edits=PersonEdits.of(shot.row))


def design_stale(shot: ShotInput, prod: ProductionInput) -> list[str]:
    """Why the stored design no longer fits the shot; ["no design"] when there is none."""
    design = shot.stored_design()
    if not design.get("pins") or not shot.row.get("ir"):
        return ["no design"]
    reasons = stale_reasons(design["pins"], shot_version=shot.version, script_hash=shot.pins.script_hash,
                            canon=prod.by_id)
    if set(Pins.model_validate(design["pins"]).canon) != set(shot.pins.canon):
        reasons.append("Different people or place in the shot.")
    intent = shot.intent
    if intent is not None and design.get("intent") and design["intent"] != intent.stamp():
        reasons.append("What the shot is for changed.")
    return reasons
