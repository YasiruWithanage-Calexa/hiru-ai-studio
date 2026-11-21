"""The Production panel (screen 3d): a shot's camera, its first frames, and its video prompt
(PLAN.md §10, §13 Phase 4).

Three things are produced per shot, in this order, and each is gated by the one before it:

1. a DESIGN (`shot_producer`): the director of photography's IR for the shot, a camera
   RECOMMENDATION in the panel's own vocabulary (`CAMERA_OPTIONS`), and why;
2. FIRST FRAMES (`frame_render`): still images a person picks from. Picking is free; accepting
   one unlocks the prompt;
3. the VIDEO PROMPT (`shot_producer`): Veo prose built in code from the IR, the camera as it
   stands now (the recommendation plus a person's changes) and the approved script.

Nothing upstream is ever redone silently. Each of the three records the PINS it was made
against (the shot's version, a hash of its script, the canon card versions of the people and
place in it); when any of those move on, the thing is reported out of date with the reason,
and a person decides whether to make it again (PLAN.md §6.1 "upstream change flags, never
redoes").

Pure standard library + pydantic (the `contracts` rule): the API, `shot_producer` and
`frame_render` share these.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from contracts import camera as cam
from contracts.canon import look_stamp, name_key
from contracts.shotplan import Item

# ── camera ─────────────────────────────────────────────────────────────────────────────────


class CameraField(StrEnum):
    FRAMING = "framing"
    ANGLE = "angle"
    LENS = "lens"
    APERTURE = "aperture"
    MOVEMENT = "movement"
    SPEED = "speed"
    AXIS = "axis"
    LIGHTING = "lighting"
    # plan/2026-11-20c D5: the Camera agent's further fields. Optional: "" = not set (a design made before the agent)
    SUPPORT = "support"
    HEIGHT = "height"
    FOCUS = "focus"
    COMPOSITION = "composition"
    TIME = "time"


# The eight fields every design has had; the five after them are optional ("" = not set).
CORE_FIELDS: tuple[CameraField, ...] = (CameraField.FRAMING, CameraField.ANGLE, CameraField.LENS,
                                        CameraField.APERTURE, CameraField.MOVEMENT, CameraField.SPEED,
                                        CameraField.AXIS, CameraField.LIGHTING)
OPTIONAL_FIELDS: tuple[CameraField, ...] = tuple(f for f in CameraField if f not in CORE_FIELDS)

# The panel's choices, field by field, from the camera catalogue (`contracts.camera`, plan/2026-11-20c D6). Mirrors the
# frontend's `src/features/production/lib/camera-options.ts`; change both together.
CAMERA_OPTIONS: dict[CameraField, tuple[str, ...]] = {
    CameraField.FRAMING: tuple(cam.SIZES.values()),
    CameraField.ANGLE: tuple(cam.ANGLES.values()),
    CameraField.LENS: cam.LENSES,
    CameraField.APERTURE: cam.APERTURES,
    CameraField.MOVEMENT: tuple(m.label for m in cam.MOVES),
    CameraField.SPEED: tuple(cam.SPEEDS.values()),
    CameraField.AXIS: tuple(cam.AXES.values()),
    CameraField.LIGHTING: cam.LIGHTING,
    CameraField.SUPPORT: tuple(cam.SUPPORTS.values()),
    CameraField.HEIGHT: tuple(cam.HEIGHTS.values()),
    CameraField.FOCUS: tuple(cam.FOCUS.values()),
    CameraField.COMPOSITION: tuple(cam.COMPOSITIONS.values()),
    CameraField.TIME: tuple(cam.TIMES.values()),
}


def _known_value(f: CameraField, value: str) -> bool:
    return value in CAMERA_OPTIONS[f] or (f in OPTIONAL_FIELDS and value == "")


def _normalised(data: Any) -> Any:
    """Old panel words ("Dolly in", "Handheld") in today's: stored designs and overrides keep validating (D6)."""
    if not isinstance(data, Mapping):
        return data
    out = dict(data)
    move = out.get("movement")
    if isinstance(move, str) and move in cam.OLD["movement"]:
        if move in cam.OLD_SUPPORT and not out.get("support"):
            out["support"] = cam.OLD_SUPPORT[move]
        out["movement"] = cam.normalise("movement", move)
    return out

# The director's shot size (Phase 3, `shots.framing`) in the panel's words. The director's
# choice wins: a recommendation never changes a shot's size, only how it is lensed and moved.
FRAMING_LABEL: dict[str, str] = {
    "WIDE": "Wide shot", "MS": "Medium shot", "MCU": "Medium close-up", "CU": "Close-up",
    "TWO": "Two-shot", "OTS": "Over-the-shoulder", "INSERT": "Insert",
}
# A sensible lens and stop for each size, used when no model is available.
_LENS_FOR: dict[str, tuple[str, str]] = {
    "WIDE": ("28mm", "f/4"), "MS": ("35mm", "f/2.8"), "MCU": ("50mm", "f/2.8"), "CU": ("85mm", "f/2"),
    "TWO": ("35mm", "f/4"), "OTS": ("50mm", "f/2.8"), "INSERT": ("50mm", "f/4"),
}


class CameraSettings(BaseModel):
    """One shot's camera, every field one of `CAMERA_OPTIONS` (the optional five may be "": not set)."""

    model_config = ConfigDict(extra="forbid")

    framing: str
    angle: str
    lens: str
    aperture: str
    movement: str
    speed: str
    axis: str
    lighting: str
    support: str = ""
    height: str = ""
    focus: str = ""
    composition: str = ""
    time: str = ""

    @model_validator(mode="before")
    @classmethod
    def _old_words(cls, data: Any) -> Any:
        return _normalised(data)

    @model_validator(mode="after")
    def _known(self) -> CameraSettings:
        for f in CameraField:
            value = getattr(self, f.value)
            if not _known_value(f, value):
                raise ValueError(f"{f.value} must be one of: {', '.join(CAMERA_OPTIONS[f])}")
        return self

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> CameraSettings:
        """The camera as it stands: the recommendation with a person's changes on top. A change
        that is no longer a valid choice is ignored rather than breaking the shot. An old word
        ("Dolly in") counts as today's ("Push in")."""
        data = self.model_dump()
        for key, value in (_normalised(overrides) or {}).items():
            if key in data and isinstance(value, str) and value and value in CAMERA_OPTIONS[CameraField(key)]:
                data[key] = value
        return CameraSettings.model_validate(data)


class CameraUpdate(BaseModel):
    """A person's change to a shot's camera. A field set to null goes back to the recommendation."""

    model_config = ConfigDict(extra="forbid")

    framing: str | None = None
    angle: str | None = None
    lens: str | None = None
    aperture: str | None = None
    movement: str | None = None
    speed: str | None = None
    axis: str | None = None
    lighting: str | None = None
    support: str | None = None
    height: str | None = None
    focus: str | None = None
    composition: str | None = None
    time: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _old_words(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and isinstance(data.get("movement"), str):
            return {**data, "movement": cam.normalise("movement", data["movement"])}
        return data

    @model_validator(mode="after")
    def _known(self) -> CameraUpdate:
        for f in CameraField:
            value = getattr(self, f.value)
            if value is not None and value not in CAMERA_OPTIONS[f]:
                raise ValueError(f"{f.value} must be one of: {', '.join(CAMERA_OPTIONS[f])}")
        return self


def lighting_for(heading: str, time_of_day: str) -> str:
    """A lighting preset from the scene heading: interior or exterior, and the time of day."""
    exterior = (heading or "").strip().upper().startswith(("EXT", "I/E", "INT/EXT"))
    time = f"{time_of_day} {heading}".upper()
    if "NIGHT" in time:
        return "Night, moonlight" if exterior else "Night, lamp key"
    if "DAWN" in time or ("MORNING" in time and "EARLY" in time):
        return "Dawn, soft ambient"
    if any(t in time for t in ("DUSK", "EVENING", "SUNSET", "TWILIGHT")):
        return "Dusk, soft ambient"
    return "Day, open sun" if exterior else "Day, window light"


HOLD = cam.MOVE["hold"].label


def default_camera(framing: str, *, heading: str = "", time_of_day: str = "") -> CameraSettings:
    """The rule-based recommendation: the director's size, a lens and stop that suit it, a
    camera that holds at eye level on side A, and light from the scene heading. Since plan/2026-11-20c the Camera agent
    designs the camera; this stays for a clip the agent could not design (D10) and a shot no agent has seen."""
    lens, stop = _LENS_FOR.get(framing, ("35mm", "f/2.8"))
    return CameraSettings(framing=FRAMING_LABEL.get(framing, "Medium shot"), angle="Eye level", lens=lens,
                          aperture=stop, movement=HOLD, speed="None", axis=CAMERA_OPTIONS[CameraField.AXIS][0],
                          lighting=lighting_for(heading, time_of_day))


def is_hold(camera: CameraSettings) -> bool:
    """The camera does not move (a hold, or a float, which the video model renders still: plan/2026-11-20c D7)."""
    return cam.slug_of("movement", camera.movement) in cam.HOLDS


def storyboard_note(camera: CameraSettings, trigger: str = "") -> str:
    """The note under a storyboard tile: "50mm · slow push in on L4" (the trigger only from the Camera agent's design,
    while a person has not changed the move)."""
    move = camera.movement.lower() if camera.speed in ("None", "Medium") or is_hold(camera) \
        else f"{camera.speed.lower()} {camera.movement.lower()}"
    on = f" on {trigger}" if trigger and not is_hold(camera) else ""
    return f"{camera.lens} · {move}{on}"


def camera_sentence(camera: CameraSettings) -> str:
    """The camera in one sentence of plain filmmaking words (for prompts)."""
    move = ("Locked-off, no camera movement" if is_hold(camera)
            else f"{camera.speed.lower() + ' ' if camera.speed != 'None' else ''}{camera.movement.lower()}, "
                 "one smooth move")
    depth = "shallow depth of field" if camera.aperture in ("f/1.8", "f/2", "f/2.8") else "deep focus"
    shot = f"{camera.framing}, {camera.angle.lower()}, {camera.lens} lens at {camera.aperture}, {depth}"
    return f"{shot}. {move[0].upper()}{move[1:]}."


# ── checks ─────────────────────────────────────────────────────────────────────────────────


Tone = Literal["pass", "advisory", "fail"]

# What a person can ignore on a shot, by topic. A check's `code` is stable where its label is not
# ("Crosses the axis · Side B (unlike S01)"), so an ignored topic stays ignored as the wording moves.
CHECK_TOPICS: dict[str, tuple[str, ...]] = {
    "axis": ("axis", "180", "cross"),
    "speaker_size": ("speaker", "hard to see", "size", "framing"),
    "wardrobe": ("wardrobe", "costume", "clothes", "outfit"),
    "voice_pin": ("voice",),
    # contracts.staging: who is seen vs heard, and a scene's variety of setups
    "staging": ("staging", "on screen", "heard", "seen", "visible"),
    "coverage": ("coverage", "same setup", "every shot", "variety"),
}


def check_code(text: str) -> str | None:
    """A topic a person named ("the axis warning") → its check code; None when it names none."""
    key = " ".join(str(text or "").lower().replace("_", " ").split())
    if key.replace(" ", "_") in CHECK_TOPICS:
        return key.replace(" ", "_")
    return next((code for code, words in CHECK_TOPICS.items() if any(w in key for w in words)), None)


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    tone: Tone


class CameraCheck(Check):
    """A check on the camera card: it has a topic a person can ignore for one shot."""

    code: str = ""  # the topic (`CHECK_TOPICS`), "" for a check a person cannot ignore
    waived: bool = False  # a person chose to ignore this advisory on this shot


def apply_waivers(checks: Iterable[CameraCheck], waived: Iterable[str]) -> list[CameraCheck]:
    """The checks with the topics a person ignored marked. Only advisories can be ignored: a
    passing check has nothing to ignore and a failing one blocks."""
    ignored = set(waived)
    return [c.model_copy(update={"waived": True}) if c.tone == "advisory" and c.code in ignored else c
            for c in checks]


# ── what a person set on a shot ────────────────────────────────────────────────────────────


class CastEdits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    add: list[str] = Field(default_factory=list)  # canon entity ids put in the shot by hand
    remove: list[str] = Field(default_factory=list)  # canon entity ids taken out of it by hand


class PersonEdits(BaseModel):
    """A shot's own marks by a PERSON (`shots.person_edits`): who is in it, which advisories to
    ignore, the DoP's note. Written by the API and the director chat for a person's own words,
    never by an agent, so a re-design or a re-split of the script never undoes them silently."""

    model_config = ConfigDict(extra="ignore")

    cast: CastEdits = Field(default_factory=CastEdits)
    waived_checks: list[str] = Field(default_factory=list)  # `Check.code`s
    dop_note: str = Field(default="", max_length=600)  # replaces the DP's own rationale when set
    # plan/2026-11-11b: a person turned off the same-setup frame for this shot (`contracts.frame_brief.setup_frame`)
    setup_frame_off: bool = False
    # plan/2026-11-13 §3.5 (D-A): the fields a person set through Zora ("size", "lens", "sees" ...): no model may write
    # them. The take is `shots.duration_locked`, not here.
    zora_locks: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, shot: Mapping[str, Any] | None) -> PersonEdits:
        """From a stored shot row; damaged or missing JSON reads as no edits."""
        try:
            return cls.model_validate((shot or {}).get("person_edits") or {})
        except ValueError:
            return cls()

    def dump(self) -> dict[str, Any]:
        """The stored form: only what is set, so an untouched shot stores {}."""
        out: dict[str, Any] = {}
        if self.cast.add or self.cast.remove:
            out["cast"] = {"add": self.cast.add, "remove": self.cast.remove}
        if self.waived_checks:
            out["waived_checks"] = self.waived_checks
        if self.dop_note:
            out["dop_note"] = self.dop_note
        if self.setup_frame_off:
            out["setup_frame_off"] = True
        if self.zora_locks:
            out["zora_locks"] = list(self.zora_locks)
        return out


class CastMember(BaseModel):
    """What a check or a prompt needs to know about one canon entity in a shot."""

    model_config = ConfigDict(extra="ignore")

    id: str
    code: str
    name: str
    kind: str = "character"
    version: int | None = None
    wardrobe_anchor: str = ""
    voice_pin: str = ""
    appearance: str = ""
    gender: str = ""
    # The wardrobe of the look this person wears in the shot (`contracts.canon.look_wardrobe`);
    # "" = no look, the card's wardrobe anchor applies.
    look: str = ""
    # plan/2026-11-12c: the person's state in this scene only (`scene_looks.condition`: wet from the rain, lying still)
    condition: str = ""


def camera_checks(*, index: int, cameras: list[CameraSettings], framing: str, sound_mode: str,
                  cast: list[CastMember], speaker_ids: list[str], frame_strategy: str,
                  first_code: str = "S01", previous_code: str = "") -> list[CameraCheck]:
    """Free checks for the camera card, from the camera as it stands now across the scene."""
    camera = cameras[index]
    checks: list[CameraCheck] = []
    side = camera.axis.split(" ·")[0]
    if index == 0:
        checks.append(CameraCheck(label=f"Establishes axis · {side}", tone="pass", code="axis"))
    elif camera.axis == cameras[0].axis:
        checks.append(CameraCheck(label=f"Axis matches {first_code}", tone="pass", code="axis"))
    else:
        checks.append(CameraCheck(label=f"Crosses the axis · {side} (unlike {first_code})", tone="advisory",
                                  code="axis"))
    if frame_strategy == "carry_last_frame" and previous_code:
        checks.append(CameraCheck(label=f"Opens on {previous_code}'s last frame", tone="pass"))
    if sound_mode == "dialogue" and framing in ("WIDE", "INSERT"):
        checks.append(CameraCheck(label="Speaker is hard to see in this size", tone="advisory", code="speaker_size"))
    by_id = {c.id: c for c in cast}
    for c in cast:
        if c.kind == "character":
            label = f"Wardrobe · {c.name}" if c.wardrobe_anchor else f"No wardrobe anchor · {c.name}"
            checks.append(CameraCheck(label=label, tone="pass" if c.wardrobe_anchor else "advisory", code="wardrobe"))
    for sid in speaker_ids:
        speaker = by_id.get(sid)
        if speaker is not None and not speaker.voice_pin:
            checks.append(CameraCheck(label=f"No voice pin · {speaker.name}", tone="advisory", code="voice_pin"))
    return checks


# ── what a shot was made against ───────────────────────────────────────────────────────────


class LookPin(BaseModel):
    """The look a frame was painted with: which one, and its wardrobe and sheet at the time."""

    model_config = ConfigDict(extra="ignore")

    id: str
    stamp: str  # contracts.canon.look_stamp
    name: str = ""  # for messages only; renaming a look does not make a frame stale

    @classmethod
    def of(cls, look: Mapping[str, Any]) -> LookPin:
        return cls(id=str(look["id"]), stamp=look_stamp(look), name=str(look.get("name") or ""))


class Pins(BaseModel):
    """What a design, a frame or a prompt was made against. Compared on read; never redone."""

    model_config = ConfigDict(extra="ignore")

    shot_version: int = Field(ge=1)
    script_hash: str
    canon: dict[str, int] = Field(default_factory=dict)  # canon entity id → card version
    looks: dict[str, LookPin] = Field(default_factory=dict)  # character id → look (frames only)
    # plan/2026-11-20d D8 (`contracts.picture_pins`): the camera fields that shape the still (and, on a frame, the shot
    # prompt's opening it was drawn from), and those that shape the motion. {} = made before they were pinned.
    picture: dict[str, str] = Field(default_factory=dict)
    motion: dict[str, str] = Field(default_factory=dict)


def shot_items(items: list[Item], start: int, end: int) -> list[Item]:
    return [i for i in items if start <= i.index < end]


def script_hash(scene: Mapping[str, Any], items: Iterable[Item]) -> str:
    """A shot's material as written: its blocks and lines verbatim, and the scene's place and
    time. An in-place edit to an action line changes this even when nothing the timing kernel
    measures does (`contracts.sceneplan.MATERIAL`)."""
    body = {"heading": scene.get("heading") or "", "time": scene.get("time_of_day") or "",
            "location": str(scene.get("location_id") or ""),
            "blocks": [[i.kind, i.text, i.speaker, i.delivery, i.line_id or ""] for i in items]}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _mentions(text_key: str, names: Iterable[str]) -> bool:
    padded = f" {text_key} "
    return any(k and f" {k} " in padded for k in (name_key(n) for n in names))


def pictured_text(items: Iterable[Item]) -> str:
    """The words of a shot's blocks that the camera shows. Information ("It is her father") and a
    thought ("He had no idea ...") name people who are not necessarily there, so they do not count
    (plan/2026-11-01b)."""
    return " ".join(i.text for i in items
                    if not i.is_line and not (i.kind == "action" and i.screen in ("info", "inner")))


def cast_in(items: Iterable[Item], characters: Sequence[Mapping[str, Any]],
            edits: PersonEdits | None = None) -> list[str]:
    """The canon characters in a shot: who speaks in it, then who its action shows (by name or
    alias), in canon order, then what a person added or took out by hand (`edits`). Shared, so
    the producer pins and the API checks the same people."""
    items = list(items)
    ids = {i.speaker_id for i in items if i.is_line and i.speaker_id}
    action = name_key(pictured_text(items))
    for c in characters:
        if str(c["id"]) not in ids and _mentions(action, [str(c["name"]), *(c.get("aliases") or [])]):
            ids.add(str(c["id"]))
    if edits is not None:
        ids = (ids | set(edits.cast.add)) - set(edits.cast.remove)
    return [str(c["id"]) for c in characters if str(c["id"]) in ids]


def shot_canon_ids(scene: Mapping[str, Any], cast_ids: Iterable[str], edits: PersonEdits | None = None) -> list[str]:
    """Every canon entity a shot is made against, in order: its people, the scene's place, then
    what a person added by hand; what they took out is left out (the place too)."""
    ids = [*cast_ids, *([str(scene["location_id"])] if scene.get("location_id") else [])]
    if edits is not None:
        ids = [i for i in [*ids, *edits.cast.add] if i not in set(edits.cast.remove)]
    return list(dict.fromkeys(ids))


def pins_for(*, shot_version: int, scene: Mapping[str, Any], items: Iterable[Item], cast_ids: Iterable[str],
             versions: Mapping[str, int | None], edits: PersonEdits | None = None,
             looks: Mapping[str, Mapping[str, Any]] | None = None) -> Pins:
    """`versions`: canon entity id → current card version. The scene's location is pinned too.
    `edits`: a person's additions (any canon entity, a prop or a place as well as a person) and
    removals (the scene's place too) for this shot. `looks`: character id → the look in force
    (`contracts.canon.looks_in_force`), pinned for those in the shot."""
    ids = shot_canon_ids(scene, cast_ids, edits)
    return Pins(shot_version=shot_version, script_hash=script_hash(scene, items),
                canon={i: int(versions[i] or 0) for i in ids if i in versions},
                looks=look_pins(ids, looks or {}))


def look_pins(ids: Iterable[str], looks: Mapping[str, Mapping[str, Any]]) -> dict[str, LookPin]:
    return {i: LookPin.of(looks[i]) for i in ids if i in looks}


# plan/2026-11-20d D8: what each pinned camera field is called in a reason, and the fields stored as a short hash (long
# text: a change is named, never shown)
PIN_LABELS = {"framing": "size", "angle": "angle", "height": "height", "lens": "lens", "aperture": "stop",
              "focus": "focus", "composition": "composition", "axis": "side of the line", "lighting": "lighting",
              "opens_on": "opening picture", "movement": "move", "speed": "speed", "start_s": "start",
              "end_s": "settle", "trigger": "trigger", "lands_on": "where it lands", "end_size": "end size",
              "sentence": "camera sentence"}
HASHED_PINS = ("opens_on", "lands_on", "sentence", "opening")
OPENING_REWRITTEN = "The shot's prompts were rewritten: a new opening state."
BEFORE_CAMERA = "Made before the Camera agent designed this shot: it shows the old camera."


def camera_changes(was: Mapping[str, str] | None, now: Mapping[str, str] | None, *, head: str) -> list[str]:
    """The named fields of a picture or motion pin that moved, before → after (D8): ["The camera changed: angle eye
    level → low; height eye → hip."]. Only the fields `was` pinned count (an older pin knows fewer); the shot prompt's
    `opening` is its own sentence. [] when nothing moved or nothing was pinned."""
    if not was:
        return []
    now = now or {}
    bits, out = [], []
    for key, before in was.items():
        after = str(now.get(key) or "")
        if str(before or "") == after:
            continue
        if key == "opening":
            out.append(OPENING_REWRITTEN)
        elif key in HASHED_PINS:
            bits.append(f"{PIN_LABELS.get(key, key)} changed")
        else:
            bits.append(f"{PIN_LABELS.get(key, key)} {str(before or 'not set').lower()} → {after.lower() or 'not set'}")
    return ([f"{head}: {'; '.join(bits)}."] if bits else []) + out


def stale_reasons(pins: Pins | Mapping[str, Any] | None, *, shot_version: int, script_hash: str,
                  canon: Mapping[str, CastMember], looks: Mapping[str, LookPin] | None = None,
                  picture: Mapping[str, str] | None = None, motion: Mapping[str, str] | None = None,
                  designed: bool = False) -> list[str]:
    """Why something made against `pins` is out of date now ([] when it is current).
    `canon`: the production's entities by id, with their current version. `looks`: the looks the
    shot's people wear now (`look_pins`); given for frames only, which are painted with them.
    `picture` / `motion` (plan/2026-11-20d D8, `contracts.picture_pins`): the shot's pins now, compared with what was
    pinned when given (a frame: picture; a video prompt and a shot prompt: both).
    `designed`: the Camera agent designed this shot. Then something pinned with no camera at all was made before that
    design (an older frame or prompt, or one the legacy engine wrote) and is out of date: it shows the old camera
    (the audit of 2026-11-21: a "tripod, does not move at all" prompt passed as current)."""
    if not pins:
        return []
    p = pins if isinstance(pins, Pins) else Pins.model_validate(pins)
    reasons: list[str] = []
    unpinned = (picture is not None and not p.picture) or (motion is not None and not p.motion)
    if designed and unpinned:
        reasons.append(BEFORE_CAMERA)
    else:
        if picture is not None:
            reasons += camera_changes(p.picture, picture, head="The camera changed")
        if motion is not None:
            reasons += camera_changes(p.motion, motion, head="The camera move changed")
    if p.shot_version != shot_version:
        reasons.append("The shot changed (its length, size, sound or join).")
    if p.script_hash != script_hash:
        reasons.append("The script for this shot changed.")
    for entity_id, version in p.canon.items():
        c = canon.get(entity_id)
        if c is None:
            reasons.append("Someone in this shot was removed from the canon.")
        elif int(c.version or 0) != version:
            reasons.append(f"{c.code} {c.name} has a new card (v{c.version}; this used v{version}).")
    if looks is not None:
        for entity_id in dict.fromkeys([*p.looks, *looks]):
            was, now, c = p.looks.get(entity_id), looks.get(entity_id), canon.get(entity_id)
            who = f"{c.code} {c.name}" if c else "Someone in this shot"
            if now is None and was is not None:
                reasons.append(f"{who} no longer wears the look “{was.name}”.")
            elif now is not None and (was is None or was.id != now.id):
                reasons.append(f"{who} wears the look “{now.name}” now.")
            elif now is not None and was is not None and was.stamp != now.stamp:
                reasons.append(f"{who}'s look “{now.name}” changed.")
    return reasons


# ── first frame ────────────────────────────────────────────────────────────────────────────


def identity_line(c: CastMember) -> str:
    """How one person must look in every frame: appearance, then their look's wardrobe, or the
    card's wardrobe anchor when they wear no look."""
    if c.look:
        dress = f"as in their look sheet: {c.look.strip(' .')}"
    else:
        dress = f"wearing {c.wardrobe_anchor.strip(' .')}" if c.wardrobe_anchor else ""
    bits = [b for b in (c.appearance.strip(" ."), dress) if b]
    return f"{c.name}: {'; '.join(bits)}" if bits else c.name


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


class FrameStage(StrEnum):
    """A first frame is first tried small (a DRAFT, painted at low quality: cheap, to settle the picture) and then
    painted for real (the FINAL, medium quality). Only a final can open the video prompt; an accepted draft is a
    reference a final may be painted from."""

    DRAFT = "draft"
    FINAL = "final"


def frame_stage(row: Mapping[str, Any]) -> FrameStage:
    """A frame row's stage; a row from before stages existed is a final."""
    return FrameStage.DRAFT if row.get("stage") == FrameStage.DRAFT else FrameStage.FINAL


# The image quality a person may pick for a first frame (2026-11-14): low or medium, never high for now. Not picked =
# the configured final quality (`OPENAI__IMAGE_QUALITY`, medium).
FrameQuality = Literal["low", "medium"]
FRAME_QUALITIES: tuple[str, ...] = ("low", "medium")


def frame_quality(state: Mapping[str, Any]) -> str:
    """The quality a job's state names for its first frames, or "" (the configured default). Anything else, high
    included, is ignored."""
    quality = str(state.get("quality") or "")
    return quality if quality in FRAME_QUALITIES else ""


# The label the draft goes by when it is attached to a final. The prompt keys on its start, as it does for sheets.
DRAFT_LABEL = "the approved draft of this frame"


# The first frame's prompt is `contracts.frame_brief.frame_prompt` (plan/2026-11-11b).


# ── the video prompt ───────────────────────────────────────────────────────────────────────


class PromptSegment(BaseModel):
    """Exactly one of the two. Sinhala is kept apart so the UI can render it as Sinhala."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    sinhala: str | None = None

    @model_validator(mode="after")
    def _one(self) -> PromptSegment:
        if (self.text is None) == (self.sinhala is None):
            raise ValueError("a segment is text or sinhala")
        return self

    @model_serializer
    def _only_the_one(self) -> dict[str, str]:
        """`{"text": ...}` or `{"sinhala": ...}`, never both keys (the frontend's PromptSegment)."""
        return {"text": self.text} if self.text is not None else {"sinhala": self.sinhala or ""}


class PromptSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    segments: list[PromptSegment]


def prompt_text(sections: Iterable[PromptSection | Mapping[str, Any]]) -> str:
    """The plain-text prompt, as copied to Flow. Same shape as the frontend's `promptToText`."""
    out = []
    for s in sections:
        sec = s if isinstance(s, PromptSection) else PromptSection.model_validate(s)
        body = "".join(seg.text if seg.text is not None else (seg.sinhala or "") for seg in sec.segments)
        out.append(f"{sec.title.upper()}\n{body}")
    return "\n\n".join(out)


_SINHALA = re.compile(r"[඀-෿]")


def has_sinhala(text: str) -> bool:
    return bool(_SINHALA.search(text or ""))
