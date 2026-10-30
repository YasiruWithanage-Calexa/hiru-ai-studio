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
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    source: str = ""  # "extract" | "user"
    created_by: UUID | None = None
    created_at: datetime


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
    # The current card's reference sheet, through /files/{ticket} ("" when there is none).
    reference_sheet_url: str = ""
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
    # The newest look sheet, through /files/{ticket} ("" until one is made).
    sheet_url: str = ""
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


def look_wardrobe(look: Mapping[str, Any]) -> str:
    """"outfit a cream blouse; hair loose; makeup natural; accessories gold earrings": what a
    person wrote, for a frame prompt's People line."""
    bits = [(k, _clean(str(look.get(k) or ""))) for k in ("outfit", "hair", "makeup", "accessories")]
    return "; ".join(f"{k} {v}" for k, v in bits if v)


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
# Anyone the card does not confirm as an adult man or woman is shown in plain everyday clothes.
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


def _is_adult(age: str) -> bool:
    """True only when the card gives an age of 18 or more ("late 20s" reads as 20). No number, no
    adult: a child, or a card that does not say, is never shown in the bare-skin outfits."""
    found = re.search(r"\d+", age or "")
    return found is not None and int(found.group()) >= 18


def reference_sheet_prompt(kind: CanonKind, name: str, card: CanonCard, *, aspect_ratio: str = "16:9") -> str:
    """The image prompt for an entity's reference sheet (used by frame_render, Phase 4).

    Static wording first and the entity's facts last, so the prompt cache sees one shared
    prefix across a production's sheets. A character's story wardrobe is left out on purpose:
    the sheet shows who they are, and the look they wear in a shot comes from the card."""
    aspect_ratio = reference_sheet_aspect(kind, aspect_ratio)
    if kind is CanonKind.CHARACTER:
        head = _SHEET_LAYOUT + _BASE_SHEET_RULES
        sex = _sheet_sex(card.gender)
        adult = _is_adult(card.age) and bool(sex)
        facts = [f"Name: {name}", f"Subject: one adult {sex}" if adult else "Subject: one person",
                 f"Age: {_clean(card.age)}", f"Appearance: {_clean(card.appearance)}",
                 f"Outfit in every panel: {_SHEET_OUTFIT[sex] if adult else _SHEET_OUTFIT_CLOTHED}"]
    elif kind is CanonKind.LOCATION:
        head = ("Location reference plate for a Sri Lankan television drama. Photorealistic, "
                "wide establishing view at eye level, natural light, no people, no text, no logos.")
        facts = [f"Location: {name}", f"Look: {_clean(card.look) or _clean(card.summary)}"]
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
