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

import re
import unicodedata
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


def reference_sheet_prompt(kind: CanonKind, name: str, card: CanonCard, *, aspect_ratio: str = "16:9") -> str:
    """The image prompt for an entity's reference sheet (used by frame_render, Phase 4).

    Static wording first and the entity's facts last, so the prompt cache sees one shared
    prefix across a production's sheets."""
    if kind is CanonKind.CHARACTER:
        head = ("Character reference sheet for a Sri Lankan television drama. Photorealistic, "
                "neutral studio background, soft even light. Show the same person three times: "
                "front, three-quarter and profile, full body, standing still, neutral expression. "
                "No text, no logos, no other people.")
        facts = [f"Name: {name}", f"Age: {_clean(card.age)}", f"Gender: {_clean(card.gender)}",
                 f"Appearance: {_clean(card.appearance)}", f"Wardrobe: {_clean(card.wardrobe)}"]
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
