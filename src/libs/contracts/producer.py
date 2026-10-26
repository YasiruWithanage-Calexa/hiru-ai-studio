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

from contracts.canon import name_key
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


# The panel's choices, field by field. Mirrors the frontend's
# `src/features/production/lib/camera-options.ts`; change both together.
CAMERA_OPTIONS: dict[CameraField, tuple[str, ...]] = {
    CameraField.FRAMING: ("Wide shot", "Medium shot", "Medium close-up", "Close-up", "Two-shot",
                          "Over-the-shoulder", "Insert"),
    CameraField.ANGLE: ("Eye level", "Low angle", "High angle", "Overhead"),
    CameraField.LENS: ("28mm", "35mm", "50mm", "85mm"),
    CameraField.APERTURE: ("f/1.8", "f/2", "f/2.8", "f/4", "f/5.6"),
    CameraField.MOVEMENT: ("Static", "Dolly in", "Dolly out", "Pan", "Handheld"),
    CameraField.SPEED: ("None", "Slow", "Medium", "Fast"),
    CameraField.AXIS: ("Side A · left to right", "Side B · right to left"),
    CameraField.LIGHTING: ("Night, lamp key", "Night, moonlight", "Day, window light", "Day, open sun",
                           "Dawn, soft ambient", "Dusk, soft ambient"),
}

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
    """One shot's camera, every field one of `CAMERA_OPTIONS`."""

    model_config = ConfigDict(extra="forbid")

    framing: str
    angle: str
    lens: str
    aperture: str
    movement: str
    speed: str
    axis: str
    lighting: str

    @model_validator(mode="after")
    def _known(self) -> CameraSettings:
        for f in CameraField:
            value = getattr(self, f.value)
            if value not in CAMERA_OPTIONS[f]:
                raise ValueError(f"{f.value} must be one of: {', '.join(CAMERA_OPTIONS[f])}")
        return self

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> CameraSettings:
        """The camera as it stands: the recommendation with a person's changes on top. A change
        that is no longer a valid choice is ignored rather than breaking the shot."""
        data = self.model_dump()
        for key, value in (overrides or {}).items():
            if key in data and isinstance(value, str) and value in CAMERA_OPTIONS[CameraField(key)]:
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


def default_camera(framing: str, *, heading: str = "", time_of_day: str = "") -> CameraSettings:
    """The rule-based recommendation: the director's size, a lens and stop that suit it, a
    locked-off camera at eye level on side A, and light from the scene heading."""
    lens, stop = _LENS_FOR.get(framing, ("35mm", "f/2.8"))
    return CameraSettings(framing=FRAMING_LABEL.get(framing, "Medium shot"), angle="Eye level", lens=lens,
                          aperture=stop, movement="Static", speed="None", axis=CAMERA_OPTIONS[CameraField.AXIS][0],
                          lighting=lighting_for(heading, time_of_day))


def storyboard_note(camera: CameraSettings) -> str:
    """The note under a storyboard tile: "50mm · dolly in"."""
    move = camera.movement.lower() if camera.speed in ("None", "Medium") or camera.movement == "Static" \
        else f"{camera.speed.lower()} {camera.movement.lower()}"
    return f"{camera.lens} · {move}"


def camera_sentence(camera: CameraSettings) -> str:
    """The camera in one sentence of plain filmmaking words (for prompts)."""
    move = ("Locked-off, no camera movement" if camera.movement == "Static"
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


class Pins(BaseModel):
    """What a design, a frame or a prompt was made against. Compared on read; never redone."""

    model_config = ConfigDict(extra="ignore")

    shot_version: int = Field(ge=1)
    script_hash: str
    canon: dict[str, int] = Field(default_factory=dict)  # canon entity id → card version


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


def cast_in(items: Iterable[Item], characters: Sequence[Mapping[str, Any]],
            edits: PersonEdits | None = None) -> list[str]:
    """The canon characters in a shot: who speaks in it, then who its action names (by name or
    alias), in canon order, then what a person added or took out by hand (`edits`). Shared, so
    the producer pins and the API checks the same people."""
    items = list(items)
    ids = {i.speaker_id for i in items if i.is_line and i.speaker_id}
    action = name_key(" ".join(i.text for i in items if not i.is_line))
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
             versions: Mapping[str, int | None], edits: PersonEdits | None = None) -> Pins:
    """`versions`: canon entity id → current card version. The scene's location is pinned too.
    `edits`: a person's additions (any canon entity, a prop or a place as well as a person) and
    removals (the scene's place too) for this shot."""
    return Pins(shot_version=shot_version, script_hash=script_hash(scene, items),
                canon={i: int(versions[i] or 0) for i in shot_canon_ids(scene, cast_ids, edits) if i in versions})


def stale_reasons(pins: Pins | Mapping[str, Any] | None, *, shot_version: int, script_hash: str,
                  canon: Mapping[str, CastMember]) -> list[str]:
    """Why something made against `pins` is out of date now ([] when it is current).
    `canon`: the production's entities by id, with their current version."""
    if not pins:
        return []
    p = pins if isinstance(pins, Pins) else Pins.model_validate(pins)
    reasons: list[str] = []
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
    return reasons


# ── first frame ────────────────────────────────────────────────────────────────────────────


def identity_line(c: CastMember) -> str:
    """How one person must look in every frame: appearance, then the wardrobe anchor."""
    bits = [b for b in (c.appearance.strip(" ."), f"wearing {c.wardrobe_anchor.strip(' .')}"
                        if c.wardrobe_anchor else "") if b]
    return f"{c.name}: {'; '.join(bits)}" if bits else c.name


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def frame_prompt(*, ir: Mapping[str, Any], camera: CameraSettings, aspect_ratio: str, cast: list[CastMember],
                 references: list[str] | None = None, recommended_framing: str = "") -> str:
    """The image prompt for a shot's first frame, from the DP's IR and the camera as it stands.

    `references` label the images attached to the call, IN ORDER ("Kamala's character sheet"),
    so the prompt can say which image is which. The framing a person chose wins over the IR's
    own composition note. Static wording first, the shot's facts after it."""
    frame = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    subjects = frame.get("subjects") if isinstance(frame, Mapping) else None
    subject_text = "; ".join(_clean(s) for s in subjects) if isinstance(subjects, list) else _clean(subjects)
    parts = ["Photorealistic still frame from a Sri Lankan television drama, shot on a cinema camera with "
             "real optics and natural imperfections."]
    if references:
        named = "; ".join(f"image {n} is {label}" for n, label in enumerate(references, start=1))
        parts.append(f"Reference images, in order: {named}. Match them exactly: the same faces, hair, build "
                     "and wardrobe, the same place. Do not redesign anyone.")
    parts.append(f"Camera: {camera_sentence(camera)}")
    if recommended_framing and camera.framing != recommended_framing:
        parts.append(f"Compose it as a {camera.framing.lower()}.")
    for text in (_clean(frame.get("composition")) if isinstance(frame, Mapping) else "", subject_text):
        if text:
            parts.append(text if text.endswith(".") else f"{text}.")
    people = [identity_line(c) for c in cast if c.kind == "character"]
    if people:
        parts.append("People: " + " | ".join(people) + ".")
    setting = (_clean(frame.get("setting")) if isinstance(frame, Mapping) else "") or _clean(ir.get("setting"))
    if setting:
        parts.append(f"Setting: {setting.rstrip('.')}.")
    light = (_clean(frame.get("lighting")) if isinstance(frame, Mapping) else "") or _clean(ir.get("lighting"))
    parts.append(f"Lighting: {(light or camera.lighting).rstrip('.')}.")
    parts.append("The people, place and everyday details are Sri Lankan.")
    parts.append("9:16 vertical framing." if aspect_ratio == "9:16" else f"{aspect_ratio} framing.")
    parts.append("A single still frame: no text, no watermark, no captions, no collage, no split panels.")
    return " ".join(parts)


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
