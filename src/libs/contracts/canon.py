"""Canon: the characters, locations and props a production must keep consistent (PLAN.md §8).

An entity (`canon_entities`) has a stable code (C01, L03, P02) and a history of versioned cards
(`canon_versions`). A shot pins the versions it was written against, so a new version marks
those shots out of date instead of silently changing them. A LOCKED entity is never rewritten
by an engine: extraction reports what it would have changed and leaves it alone.

Two strings matter more than the rest of the card because they go into every prompt verbatim:

* the WARDROBE ANCHOR: what a character wears, so Veo draws the same clothes in every shot;
* the VOICE PIN: how a character sounds, so the audio model gives every line the same voice.

The prompt builders here are pure functions so the extractor, the API and the shot producer
all phrase them the same way.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class CanonKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    PROP = "prop"


CODE_PREFIX: dict[CanonKind, str] = {
    CanonKind.CHARACTER: "C",
    CanonKind.LOCATION: "L",
    CanonKind.PROP: "P",
}
CODE_PATTERN = re.compile(r"^[CLP]\d{2,3}$")


def format_code(kind: CanonKind, number: int) -> str:
    """C01 … C99, then C100: two digits as the canon indexes write them, more when needed."""
    return f"{CODE_PREFIX[kind]}{number:02d}"


def next_code(kind: CanonKind, taken: set[str]) -> str:
    """The lowest free code of this kind."""
    n = 1
    while format_code(kind, n) in taken:
        n += 1
    return format_code(kind, n)


class CanonCard(BaseModel):
    """What the production knows about one entity. Every field is optional text: a card is
    filled as far as the documents allow and never invented beyond them."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(default="", max_length=2000)  # who / what it is, in one or two lines
    # characters
    age: str = Field(default="", max_length=60)  # "52", "60s"
    gender: str = Field(default="", max_length=40)
    appearance: str = Field(default="", max_length=600)  # face, build, hair
    wardrobe: str = Field(default="", max_length=600)  # the wardrobe anchor
    voice: str = Field(default="", max_length=300)  # timbre and manner: "low, clipped"
    accent: str = Field(default="", max_length=120)  # "a Sri Lankan (southern) accent"
    # locations
    look: str = Field(default="", max_length=800)  # architecture, materials, light
    # props
    details: str = Field(default="", max_length=800)  # colour, size, states
    notes: str = Field(default="", max_length=2000)  # continuity rules from the bible


class CanonVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    entity_id: UUID
    version: int = Field(ge=1)
    card: CanonCard
    wardrobe_anchor: str = ""
    voice_pin: str = ""
    reference_prompt: str = ""
    source: str = ""  # "extract" | "user" | "inferred" | "refine"
    # plan/2026-11-12c: field -> {source: script|inferred, line, reason} for a refined card ({} otherwise)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID | None = None
    created_at: datetime


class LocationView(BaseModel):
    """One named view of a location's views sheet (plan/2026-11-24)."""

    n: int = Field(ge=1, le=6)
    name: str = Field(min_length=1, max_length=60)
    what: str = Field(min_length=1, max_length=600)


class CanonEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    kind: CanonKind
    code: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    core: bool = False  # core cast vs supporting
    locked: bool = False
    current_version: int | None = None
    current: CanonVersion | None = None
    # plan/2026-11-12c (schema v23): a place set|vehicle|region|spot|unseen, a thing prop|mentioned (None: not classed);
    # a spot's set; and why there is no reference plate for this class ("" when there may be one)
    canon_class: str | None = Field(default=None, validation_alias=AliasChoices("canon_class", "class"))
    parent_id: UUID | None = None
    no_plate: str = ""
    # The current card's reference sheet, through /files/{ticket} ("" when there is none).
    reference_sheet_url: str = ""
    reference_sheet_thumb_url: str = ""  # its 640 px WebP, for cards (may 404 for an older sheet: use the full one)
    reference_sheet_key: str = ""  # names the sheet's file for ever; the URLs change every hour
    # plan/2026-11-14 §3.1: a character's face sheet (six views), through /files/{ticket} ("" when there is none)
    face_sheet_url: str = ""
    face_sheet_thumb_url: str = ""
    face_sheet_key: str = ""
    # plan/2026-11-24: a location's views sheet, through /files/{ticket}, and its six views ([] when there is none)
    views_sheet_url: str = ""
    views_sheet_thumb_url: str = ""
    views_sheet_key: str = ""
    views: list[LocationView] = Field(default_factory=list)
    views_layout: str = ""
    views_light: str = ""
    created_at: datetime
    updated_at: datetime


class CanonEntityUpdate(BaseModel):
    """Identity fields only; the card changes through a new version."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    aliases: list[str] | None = Field(default=None, max_length=20)
    core: bool | None = None


class CanonVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card: CanonCard
    # Explicit pins override the ones derived from the card (a person's wording wins).
    wardrobe_anchor: str | None = Field(default=None, max_length=600)
    voice_pin: str | None = Field(default=None, max_length=400)


# ── looks ──────────────────────────────────────────────────────────────────────────────────
# A character has ONE base sheet (the entity's reference sheet: who they are) and many LOOKS: what
# they wear for a stretch of episodes. A look sheet is painted from the base sheet, so face and body
# stay the same and only clothes, hair, makeup and accessories change.


class EpisodeRange(BaseModel):
    """Inclusive episode numbers. One episode is {from: 44, to: 44}."""

    model_config = ConfigDict(populate_by_name=True)

    first: int = Field(alias="from", ge=1, le=999)
    last: int = Field(alias="to", ge=1, le=999)

    @model_validator(mode="after")
    def _ordered(self) -> EpisodeRange:
        if self.last < self.first:
            raise ValueError("a range ends after it starts")
        return self


class LookFields(BaseModel):
    """What a person writes for a look. Every wardrobe field is free text; `accessories` takes
    jewelry, a watch, a cap, glasses, a bag: whatever the character carries or wears on top."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=120)
    ranges: list[EpisodeRange] = Field(min_length=1, max_length=12)
    outfit: str = Field(default="", max_length=600)
    hair: str = Field(default="", max_length=300)
    makeup: str = Field(default="", max_length=300)
    accessories: str = Field(default="", max_length=600)


class LookCreate(LookFields):
    pass


class LookUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    ranges: list[EpisodeRange] | None = Field(default=None, min_length=1, max_length=12)
    outfit: str | None = Field(default=None, max_length=600)
    hair: str | None = Field(default=None, max_length=300)
    makeup: str | None = Field(default=None, max_length=300)
    accessories: str | None = Field(default=None, max_length=600)


class CanonLook(LookFields):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)  # a row has more columns

    id: UUID
    entity_id: UUID
    status: Literal["draft", "ready"] = "draft"
    origin: Literal["person", "refine"] = "person"  # plan/2026-11-12c: "refine" = drafted by the canon refine
    # The newest look sheet, through /files/{ticket} ("" until one is made).
    sheet_url: str = ""
    sheet_thumb_url: str = ""
    sheet_key: str = ""
    created_at: datetime
    updated_at: datetime


class LooksView(BaseModel):
    episode_count: int  # episodes in the production, to find stretches no look covers
    looks: list[CanonLook]


class SceneLookChoice(BaseModel):
    """A person picks which look of a character a scene uses."""

    model_config = ConfigDict(extra="forbid")

    look_id: UUID


class SceneLook(BaseModel):
    """The look a scene uses for one character. Without one, the episode rule applies."""

    model_config = ConfigDict(extra="ignore")

    entity_id: UUID
    look_id: UUID
    # plan/2026-11-12c (schema v23): the person's state in this scene only (wet, lying still), why this look, and who
    # chose it ("refine": drafted by the canon refine; a person's choice is never replaced)
    condition: str = ""
    why: str = ""
    origin: str = "person"


class SceneConditionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: str = Field(max_length=300)


class SceneLooksView(BaseModel):
    looks: list[SceneLook]


# ── the look a scene wears (pure; the UI's `resolveLook` is the same rule) ─────────────────


def _covers(look: Mapping[str, Any], episode: int) -> bool:
    return any(int(r.get("from") or 0) <= episode <= int(r.get("to") or 0) for r in look.get("ranges") or [])


def _span(look: Mapping[str, Any]) -> int:
    return sum(int(r.get("to") or 0) - int(r.get("from") or 0) + 1 for r in look.get("ranges") or [])


def resolve_look(looks: Sequence[Mapping[str, Any]], episode: int) -> Mapping[str, Any] | None:
    """One character's look in force for an episode: the narrowest READY look that covers it.
    None when no look covers it, or when two ready looks of the same width do (ambiguous)."""
    claiming = sorted((lk for lk in looks if lk.get("status") == "ready" and _covers(lk, episode)), key=_span)
    if not claiming or (len(claiming) > 1 and _span(claiming[1]) == _span(claiming[0])):
        return None
    return claiming[0]


def looks_in_force(looks: Sequence[Mapping[str, Any]], picks: Sequence[Mapping[str, Any]],
                   episode: int | None) -> dict[str, Mapping[str, Any]]:
    """character id → the look a scene uses. A person's pick for the scene wins while that look is
    ready; otherwise the episode rule. A character with neither is left out (base sheet and card)."""
    chosen = {str(p["entity_id"]): str(p["look_id"]) for p in picks}
    by_entity: dict[str, list[Mapping[str, Any]]] = {}
    for lk in looks:
        by_entity.setdefault(str(lk["entity_id"]), []).append(lk)
    out: dict[str, Mapping[str, Any]] = {}
    for entity_id, own in by_entity.items():
        pick = next((lk for lk in own if str(lk["id"]) == chosen.get(entity_id)), None)
        if pick is not None and pick.get("status") == "ready":
            out[entity_id] = pick
        elif episode is not None and (found := resolve_look(own, episode)) is not None:
            out[entity_id] = found
    return out


def look_sheet_path(look: Mapping[str, Any]) -> str:
    """The newest look sheet in the `references` bucket ("" when none is made)."""
    assets = look.get("sheet_assets") or []
    first = assets[0] if isinstance(assets, list) and assets else None
    return str((first.get("path") if isinstance(first, dict) else first) or "")


def scene_conditions(picks: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """character id -> the scene's condition for them (`scene_looks.condition`, schema v23, plan/2026-11-12c): wet from
    the rain, lying still. It holds whatever look applies, ready or not: it is the scene's, not the outfit's."""
    found = {str(p["entity_id"]): _clean(str(p.get("condition") or "")) for p in picks}
    return {k: v for k, v in found.items() if v}


def look_wardrobe(look: Mapping[str, Any]) -> str:
    """"outfit a cream blouse; hair loose; makeup natural; accessories gold earrings": what a
    person wrote, for a frame prompt's People line."""
    bits = [(k, _clean(str(look.get(k) or ""))) for k in ("outfit", "hair", "makeup", "accessories")]
    return "; ".join(f"{k} {v}" for k, v in bits if v)


def look_outfit(look: Mapping[str, Any]) -> str:
    """"dusty-rose blouse and navy trousers, with gold stud earrings and a tan handbag": what the look puts ON the
    person, for a video prompt's Subjects line (plan/2026-11-18). Hair and makeup stay with the person's description."""
    outfit = _clean(str(look.get("outfit") or ""))
    extras = _clean(str(look.get("accessories") or ""))
    if extras.lower() in ("none", "no accessories", "n/a"):
        extras = ""
    if not outfit:
        return ""
    return f"{_sentence_case_off(outfit)}, with {_sentence_case_off(extras)}" if extras else _sentence_case_off(outfit)


def _sentence_case_off(text: str) -> str:
    """"Dusty-rose blouse" → "dusty-rose blouse", "A navy kurta" → "a navy kurta": a sentence's capital, not an
    acronym's ("NGO uniform" stays)."""
    first = text.split(" ", 1)[0]
    if first[:1].isupper() and first[1:] == first[1:].lower():
        return text[:1].lower() + text[1:]
    return text


def wardrobe_by_code(looks: Mapping[str, Mapping[str, Any]], canon: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """canon code → `look_outfit`, from `looks_in_force` (character id → look): what a video prompt's Subjects line
    dresses each person in. A person without a look, or a look without an outfit, is left out."""
    code_of = {str(c.get("id")): str(c.get("code") or "") for c in canon}
    out: dict[str, str] = {}
    for entity_id, look in looks.items():
        code, outfit = code_of.get(str(entity_id), ""), look_outfit(look)
        if code and outfit:
            out[code] = outfit
    return out


_WEARING = re.compile(r"(?:^|\s*,\s*|\s+and\s+|\s+)(?:wearing|dressed in|clad in)\b.*$", re.IGNORECASE | re.DOTALL)


def dressed(description: str, outfit: str) -> str:
    """A person's description with the clothes the scene's look gives them, in place of whatever clothes the planner
    wrote (plan/2026-11-18: Love Hour 4 shot 02's prompt said "muted blue blouse" while her look and her frame were
    dusty rose, and the video followed the words). Without an outfit the description is returned unchanged."""
    if not outfit:
        return description
    body = _WEARING.sub("", description.strip().rstrip(" .;,"))
    return f"{body}, wearing {outfit}" if body else f"wearing {outfit}"


def look_stamp(look: Mapping[str, Any]) -> str:
    """Changes when what a frame takes from a look changes (its wardrobe or its sheet), not when
    its name or episodes do."""
    body = [str(look.get(k) or "") for k in ("outfit", "hair", "makeup", "accessories")] + [look_sheet_path(look)]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest()[:12]


# ── prompt builders (pure) ─────────────────────────────────────────────────────────────────

DEFAULT_ACCENT = "a Sri Lankan (Colombo) accent"


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip(" .;,")


def voice_pin(card: CanonCard, *, default_accent: str = DEFAULT_ACCENT) -> str:
    """"low, clipped female voice (52), a Sri Lankan (southern) accent". Empty when the card
    says nothing about the voice, age or gender: an empty pin is shown as missing, not guessed."""
    style, gender, age = _clean(card.voice), _clean(card.gender).lower(), _clean(card.age)
    if not (style or gender or age):
        return ""
    base = f"{gender} voice" if gender else "voice"
    if style:
        base = f"{style} {base}"
    if age:
        base = f"{base} ({age})"
    accent = _clean(card.accent) or default_accent
    return f"{base}, {accent}"


def wardrobe_anchor(card: CanonCard) -> str:
    return _clean(card.wardrobe)


# A character's base sheet is ONE wide picture of five panels (PLAN.md §8): three full-body views
# cropped at the neck, a back view that shows the hair, and a smiling face. It shows the true
# face, skin tone, body and hair, so every look can be made from it. It is an identity reference,
# not a costume: `contracts.producer.frame_prompt` tells the image model to take clothes from the
# card, never from the sheet.
SHEET_ASPECT = "16:9"

_SHEET_OUTFIT = {
    "woman": "a plain solid-color fitted sports bra and fitted gym shorts, navy",
    "man": "plain solid-color gym shorts, navy, no shirt",
}
# A card whose gender is missing or not man/woman is shown in plain everyday clothes.
_SHEET_OUTFIT_CLOTHED = "a plain fitted grey t-shirt and fitted grey trousers, hair tied back if long"


_SHEET_LAYOUT = (
    "Character reference sheet for a Sri Lankan television drama. Photorealistic, "
    "catalog-style reference photo, high resolution, sharp focus. Plain neutral grey "
    "seamless studio background, even soft studio lighting, no shadows on the background.\n"
    "Layout: a clean grid of five panels on a single image. Left three panels: full-body "
    "views of the same person cropped at the neck so no head or face is visible. Views: "
    "front, three-quarter, side. Neutral standing pose, arms relaxed at sides, empty hands, "
    "feet visible. Fourth panel: full-body back view with the head included, seen from "
    "behind, so the full hairstyle is visible (length, parting, texture, how it falls over "
    "the shoulders and back). No face visible in this panel. Right panel: a close-up "
    "portrait of the face and shoulders, smiling naturally with teeth visible, looking at "
    "the camera.\n")
_BASE_SHEET_RULES = (
    "The same outfit, cut and color in every panel, no accessories, no jewelry. Identical "
    "skin tone, body proportions, moles or marks, and hair color, length and style in every "
    "panel. No text, no labels, no watermark, no logos, no props, no background objects, no "
    "other people, not a cartoon. Avoid: extra limbs, a different body, outfit or hairstyle "
    "between panels, a head on the front, three-quarter or side panels.")
_LOOK_SHEET_RULES = (
    "Image 1 is the base character sheet of this same person. Keep their face, skin tone, body "
    "proportions, height, moles or marks exactly as in image 1. The clothes on image 1 are only a plain "
    "reference outfit: replace them completely with the outfit below. Change nothing but what the facts "
    "list; anything not listed stays as in image 1.\n"
    "The same outfit and accessories, cut and color, in every panel. Headwear, glasses and earrings show "
    "only in the panels where the head is visible; a watch, bracelets and rings show on the hands. No "
    "text, no labels, no watermark, no logos, no props, no background objects, no other people, not a "
    "cartoon. Avoid: extra limbs, a different body or face, a different outfit or hairstyle between "
    "panels, a head on the front, three-quarter or side panels.")


def reference_sheet_aspect(kind: CanonKind, aspect_ratio: str = "16:9") -> str:
    """A character's sheet is always wide, whatever the production's orientation."""
    return SHEET_ASPECT if kind is CanonKind.CHARACTER else aspect_ratio


def _sheet_sex(gender: str) -> str:
    text = _clean(gender).lower()
    if re.search(r"\b(female|woman|women|girl)\b", text):
        return "woman"
    if re.search(r"\b(male|man|men|boy)\b", text):
        return "man"
    return ""


def reference_sheet_prompt(kind: CanonKind, name: str, card: CanonCard, *, aspect_ratio: str = "16:9") -> str:
    """The image prompt for an entity's reference sheet (used by frame_render, Phase 4).

    Static wording first and the entity's facts last, so the prompt cache sees one shared
    prefix across a production's sheets. A character's story wardrobe is left out on purpose:
    the sheet shows who they are, and the look they wear in a shot comes from the card."""
    aspect_ratio = reference_sheet_aspect(kind, aspect_ratio)
    if kind is CanonKind.CHARACTER:
        head = _SHEET_LAYOUT + _BASE_SHEET_RULES
        sex = _sheet_sex(card.gender)
        # Every character is an adult for now (children are handled later): the gender alone picks the outfit.
        facts = [f"Name: {name}", f"Subject: one adult {sex}" if sex else "Subject: one person",
                 f"Age: {_clean(card.age)}", f"Appearance: {_clean(card.appearance)}",
                 f"Outfit in every panel: {_SHEET_OUTFIT[sex] if sex else _SHEET_OUTFIT_CLOTHED}"]
    elif kind is CanonKind.LOCATION:
        head = ("Location reference plate for a Sri Lankan television drama. Photorealistic, "
                "wide establishing view at eye level, natural light, no people, no text, no logos.")
        # never the summary (plan/2026-11-12c): a summary is the documents' words, often a whole scene with its people
        facts = [f"Location: {name}", f"Look: {_clean(card.look)}"]
    else:
        head = ("Prop reference sheet for a Sri Lankan television drama. Photorealistic, the "
                "object alone on a neutral background, two angles, soft even light, no text, no logos.")
        facts = [f"Prop: {name}", f"Details: {_clean(card.details) or _clean(card.summary)}"]
    body = "\n".join(f for f in facts if not f.endswith(": "))
    return f"{head}\nAspect ratio {aspect_ratio}.\n{body}"


def look_sheet_prompt(character: str, look: LookFields) -> str:
    """The image prompt for a look sheet: the base sheet's five-panel layout, the same person, in
    the clothes and accessories a person wrote. The base sheet goes in as image 1 (frame_render
    attaches it). Static wording first, the look's facts last. Always wide, like the base sheet."""
    facts = [f"Character: {character}", f"Look: {_clean(look.name)}", f"Outfit: {_clean(look.outfit)}",
             f"Hair: {_clean(look.hair)}", f"Makeup: {_clean(look.makeup)}",
             f"Accessories: {_clean(look.accessories)}"]
    body = "\n".join(f for f in facts if not f.endswith(": "))
    return f"{_SHEET_LAYOUT}{_LOOK_SHEET_RULES}\nAspect ratio {SHEET_ASPECT}.\n{body}"


# ── face sheets (plan/2026-11-14 §3.1) ──────────────────────────────────────────────────────

# Every base and look sheet holds ONE face (front, smiling, studio light). A face sheet gives the image model the same
# face at six angles and two expressions, so a shot that needs the person turned, serious or at night does not invent
# it. Painted from the portrait cut out of the base sheet (the face does not change with a look). Word for word the
# lab's gender-neutral prompt (lab/storyboard/faces.py, run_012/013).
FACE_SHEET_KIND = "face"
FACE_SHEET_QUALITY = "medium"  # the person's image rule (2026-11-14): never high
PORTRAIT_SHARE = 0.265  # the base sheet's right-hand portrait panel: its right 26.5 % (lab faces.py)


def face_sheet_prompt() -> str:
    """The image prompt for a face sheet. Image 1 is the portrait cut from the base sheet (`portrait_crop`)."""
    return (
        "A face reference sheet for a Sri Lankan television drama: the SAME person as image 1, photographed six times "
        "in one image, laid out 3 across and 2 down, each a head-and-shoulders photograph on the same plain mid-grey "
        "studio backdrop, separated by thin white gutters. Top row: (1) facing the camera, neutral relaxed expression, "
        "mouth closed; (2) three-quarter view, head turned toward the left of the picture, neutral; (3) three-quarter "
        "view, head turned toward the right of the picture, neutral. Bottom row: (4) full profile facing the left of "
        "the picture; (5) full profile facing the right of the picture; (6) facing the camera, serious and worried, "
        "brows slightly drawn, mouth closed. "
        "Exactly the person in image 1 in every photograph: the same face shape, age, skin tone, eyes, nose, lips, "
        "ears, hairline, hair and facial hair. Do not age them, do not make them heavier or more weathered. Only the "
        "head angle and the expression change. The same top as in image 1. Soft, even studio light from the front in "
        "every photograph. Photorealistic. No text, no numbers, no labels.")


def _asset_kind(asset: Any) -> str:
    return str(asset.get("kind") or "sheet") if isinstance(asset, Mapping) else "sheet"


def _asset_path(asset: Any) -> str:
    return str((asset.get("path") if isinstance(asset, Mapping) else asset) or "")


def sheet_assets(assets: Any) -> list[Any]:
    """A version's `reference_assets` without its face sheets and location views: the base sheets (or plates), newest
    first."""
    return [a for a in (assets if isinstance(assets, list) else [])
            if _asset_kind(a) not in (FACE_SHEET_KIND, VIEWS_SHEET_KIND)]


# ── location views (plan/2026-11-24; lab/location_views run_001, the person's method) ───────────────────────────

# ONE picture of a place in six named views (a front wide, looking left, looking right, the reverse, two details), so
# every board panel and first frame paints the same place: the person's method, proven in lab/location_views. Stored
# as a `reference_assets` entry of this kind on the location's current card, with its views and their boxes.
VIEWS_SHEET_KIND = "views"
VIEWS_SHEET_QUALITY = "medium"  # the person's image rule: never high; the lab painted it at medium
VIEWS_COUNT = 6
VIEWS_ASPECT = "16:9"  # 1536x1024: six landscape views, 3 across and 2 down
VIEWS_LABEL_HEAD = "the location sheet for "


def views_asset(row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The newest location views sheet of a location's current card, or None."""
    assets = (row.get("current") or {}).get("reference_assets") or []
    return next((a for a in assets if isinstance(a, Mapping) and _asset_kind(a) == VIEWS_SHEET_KIND
                 and _asset_path(a) and a.get("views")), None)


def view_of(row: Mapping[str, Any], n: int) -> Mapping[str, Any] | None:
    """View `n` (1-based) of a location's views sheet, or None."""
    asset = views_asset(row)
    return next((v for v in (asset or {}).get("views") or [] if int(v.get("n") or 0) == n), None)


def views_label(name: str) -> str:
    """How the board names the attached sheet (lab `SHEET_LABEL`)."""
    return f"{VIEWS_LABEL_HEAD}{name}: six named views of the one place"


def view_label(name: str, view: Mapping[str, Any]) -> str:
    """How a first frame names the one view it is painted against (lab `frame_prompt`)."""
    return f"view {view['n']} ({str(view['name']).lower()}) of the location sheet for {name}"


VIEW_JOB = ("the background exactly as this view shows it, the same things on the same sides, seen from this shot's "
            "own camera")


def views_sheet_prompt(place: str, plates: Sequence[str], layout: str, light: str,
                       views: Sequence[Mapping[str, Any]]) -> str:
    """The image prompt of a location views sheet (lab `sheet_prompt`). `plates`: the attached pictures' labels, in
    order (the location plate first, then the plates of the places that stand in it); `layout`: the place as one
    connected layout (the views writer's, from the board writers' geography); `light`: the light and weather every
    view shares; `views`: six `{name, what}`. Changes from the lab, said: its "take from" sentences named the roadside
    and the three-wheeler; here they come from the labels."""
    cite = "; ".join(f"image {i} is {label}" for i, label in enumerate(plates, 1))
    takes = []
    for i, label in enumerate(plates, 1):
        if i == 1:
            takes.append("Take from image 1 the place itself: its ground, walls, buildings, plants, poles and fixed "
                         "things, their materials and colours.")
        else:
            what = label.split(" for ", 1)[-1]
            takes.append(f"Take from image {i} the {what} exactly as shown; it stands in this place.")
    lines = "\n".join(f"VIEW {i} (row {(i - 1) // 3 + 1}, column {(i - 1) % 3 + 1}) — {v['name']}: {v['what']}"
                      for i, v in enumerate(views, 1))
    return "\n\n".join(x for x in [
        "A location reference sheet for a Sri Lankan television drama: six photorealistic film stills of ONE real "
        "place, laid out in a grid 3 across and 2 down, read left to right, then top to bottom. Every still is a "
        "landscape 3:2 picture of the same size, separated by thin, even, plain white gutters. Nobody is in any "
        "view: no people, no figures.",
        (f"Reference images, in order: {cite}. " + " ".join(takes)) if plates else "",
        f"The place, one connected layout seen from six positions: {layout}" if layout else "",
        f"Light and weather (every view): {light}" if light else "",
        lines,
        f"Every view shows the SAME place ({place}): the same buildings, walls and fixed things, each where the layout "
        "puts it. Draw NO text of any kind: no labels, no numbers, no captions, no arrows, no borders other than the "
        "gutters.",
    ] if x)


def face_sheet_path(row: Mapping[str, Any]) -> str:
    """The newest face sheet of a character's current card ("" when none is made)."""
    assets = (row.get("current") or {}).get("reference_assets") or []
    return next((_asset_path(a) for a in assets if _asset_kind(a) == FACE_SHEET_KIND and _asset_path(a)), "")


def missing_faces(canon: Sequence[Mapping[str, Any]], entity_ids: Iterable[str]) -> list[Mapping[str, Any]]:
    """The characters among `entity_ids` (in that order, once each) whose current card has no face sheet. Nothing
    paints one by itself (2026-11-22): the board and its frames name these people, and a person makes the sheet."""
    by_id = {str(c["id"]): c for c in canon}
    out = []
    for cid in dict.fromkeys(str(i) for i in entity_ids):
        row = by_id.get(cid)
        if row and row.get("kind") == "character" and not face_sheet_path(row):
            out.append(row)
    return out


def keep_assets(assets: Sequence[Any], sheets: int = 5, faces: int = 2, views: int = 2) -> list[Any]:
    """The `reference_assets` a version keeps, newest first: up to `sheets` sheets, `faces` face sheets and `views`
    location views sheets, so a new sheet of one kind never pushes another kind out."""
    cap = {FACE_SHEET_KIND: faces, VIEWS_SHEET_KIND: views}
    out: list[Any] = []
    seen: dict[str, int] = {}
    for a in assets:
        kind = _asset_kind(a) if _asset_kind(a) in cap else "sheet"
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] <= cap.get(kind, sheets):
            out.append(a)
    return out


def named_in(name: str, text: str) -> bool:
    """`name` appears in `text` as whole words ("photo" is not in "photographs"; plan/2026-11-12c Track B). Both are
    compared as `name_key`s."""
    key, hay = name_key(name), name_key(text)
    return bool(key) and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", hay) is not None


def props_in(props: Sequence[Mapping[str, Any]], text: str, ids: Sequence[str] | None = None) -> list[str]:
    """The names of the production's props a scene has: by canon id when the scene has a breakdown (`ids`, the
    things its brief gives a role: hero, used, worn or dressing), else the props `text` names as whole words."""
    if ids is not None:
        wanted = {str(i) for i in ids}
        return [str(p["name"]) for p in props if str(p.get("id")) in wanted]
    return [str(p["name"]) for p in props if named_in(str(p.get("name") or ""), text)]


def name_key(name: str) -> str:
    """Matching key for names: case-folded, punctuation and honorifics dropped.

    "Mrs. Perera" and "MRS PERERA" match; Sinhala passes through unchanged (casefold is a no-op
    on it). Used to match script cues and scene headings to canon entities."""
    text = (name or "").casefold()
    text = re.sub(r"\((?:v\.?o\.?|o\.?s\.?|o\.?c\.?|cont'?d)\)", " ", text)
    # Drop punctuation and symbols only. Not `[^\w]`: Sinhala vowel signs are combining marks
    # (Mn/Mc), which `\w` does not match, and ZWJ/ZWNJ (Cf) build conjuncts.
    text = "".join(" " if unicodedata.category(ch)[0] in "PSZ" else ch for ch in text)
    return " ".join(text.split())
