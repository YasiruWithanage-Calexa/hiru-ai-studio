"""The content model: Production (drama) → Episode → Scene → Shot.

Phase 0 needs only the production itself; the lower levels are defined now so every function
and the API agree on their shape from the first engine onwards. They are wire models, not ORM
models: fields here are what crosses a process boundary.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contracts.roles import AppRole, ProductionRole
from contracts.veo import (
    DEFAULT_SHOT_SECONDS,
    VEO_DURATIONS,
    CameraLink,
    FrameStrategy,
    Orientation,
    SoundMode,
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# ── production ──────────────────────────────────────────────────────────────────────────────


class ProductionKind(StrEnum):
    DRAMA_SERIES = "drama_series"
    DAILY = "daily"
    SPECIAL = "special"


class ProductionStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_DIRECTOR = "ready_for_director"
    IN_PRODUCTION = "in_production"
    ARCHIVED = "archived"


Title = Annotated[str, Field(min_length=1, max_length=200)]


class BuildOptions(_Model):
    canon: bool = True  # extract characters, locations and props
    scenes: bool = True  # episodes → scenes from the scripts
    shots: bool = True  # scenes → shot lists


class ProductionSettings(_Model):
    """Per-production settings. Changing them is admin-only (Permission.MANAGE_PRODUCTION)."""

    # Force every shot to 8 s instead of the 4/6/8 ladder (PLAN.md Q3).
    fixed_shot_seconds: int | None = None
    # Default scene envelope in seconds; shots must fit inside it, never stretched to fill it.
    default_scene_envelope_s: int = Field(default=60, ge=4, le=1800)
    # Market for accent casting ("a Sri Lankan (Colombo) accent").
    market: str = "LK"
    spoken_language: str = "si"
    # What the structure build writes (screen 0a "What AI builds").
    build: BuildOptions = Field(default_factory=BuildOptions)

    @field_validator("fixed_shot_seconds")
    @classmethod
    def _renderable(cls, v: int | None) -> int | None:
        if v is not None and v not in VEO_DURATIONS:
            raise ValueError(f"fixed_shot_seconds must be one of {VEO_DURATIONS}")
        return v


class ProductionCreate(_Model):
    title: Title
    kind: ProductionKind = ProductionKind.DRAMA_SERIES
    orientation: Orientation
    summary: str = Field(default="", max_length=4000)
    settings: ProductionSettings = Field(default_factory=ProductionSettings)


class ProductionUpdate(_Model):
    """Every field optional; only the ones sent are changed."""

    title: Title | None = None
    kind: ProductionKind | None = None
    orientation: Orientation | None = None
    status: ProductionStatus | None = None
    summary: str | None = Field(default=None, max_length=4000)
    settings: ProductionSettings | None = None


class Production(_Model):
    id: UUID
    title: str
    kind: ProductionKind
    orientation: Orientation
    status: ProductionStatus
    summary: str
    settings: ProductionSettings
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    # The caller's own role on it (None for an admin who is not a member).
    my_role: ProductionRole | None = None


# ── people ─────────────────────────────────────────────────────────────────────────────────


class Profile(_Model):
    id: UUID
    email: str
    display_name: str
    initials: str
    app_role: AppRole
    active: bool


class ProductionMember(_Model):
    user_id: UUID
    display_name: str
    email: str
    role: ProductionRole


# ── episode / scene / shot (Phase 2) ───────────────────────────────────────────────────────


class EpisodeStatus(StrEnum):
    DRAFT = "draft"  # created from an outline, no scenes yet
    BUILDING = "building"  # scenes or shots being written by the build
    READY = "ready"  # scenes and shots exist; open in the Director panel
    APPROVED = "approved"  # every scene approved


class SceneStatus(StrEnum):
    DRAFT = "draft"  # parsed from the script, not split into shots yet
    SPLIT = "split"  # has a shot list
    APPROVED = "approved"  # locked for production (Permission.APPROVE_SCENE); engines leave it alone


class ShotStatus(StrEnum):
    """How far a shot has got through the Production panel (the UI's `ShotProgress`)."""

    DRAFT = "draft"
    FRAME = "frame"  # a first frame is accepted
    PROMPT = "prompt"  # a video prompt exists


class Framing(StrEnum):
    WIDE = "WIDE"
    MS = "MS"
    MCU = "MCU"
    CU = "CU"
    TWO = "TWO"  # two-shot
    OTS = "OTS"  # over the shoulder
    INSERT = "INSERT"


class BlockKind(StrEnum):
    ACTION = "action"
    DIALOGUE = "dialogue"  # one spoken line; the text lives in `dialogue_lines`
    SOUND = "sound"
    BEAT = "beat"  # a pause or a turn the director marked
    CUT = "cut"  # an explicit transition ("CUT TO:")


class ScriptBlock(_Model):
    """One block of a scene's script, in order. Dialogue blocks point at their line by id, so
    a line's text is stored once (`dialogue_lines`) and shot binding never copies it."""

    kind: BlockKind
    text: str = ""
    line_id: UUID | None = None


class Beat(_Model):
    start_s: int = Field(ge=0)
    end_s: int = Field(gt=0)
    camera: str = ""
    director_line: str = ""
    action: str = ""


class DialogueLine(_Model):
    id: UUID
    scene_id: UUID
    ord: int = Field(ge=0)
    speaker: str  # as written in the script
    character_id: UUID | None = None  # the canon character, when matched
    text: str  # the spoken line as approved in the script (Sinhala); engines never rewrite it
    delivery: str = ""
    words: int = 0
    shot_id: UUID | None = None
    beat_index: int | None = None
    start_s: float | None = None  # from the start of the scene, set by the split kernel
    overrun_s: float = 0.0  # how far it runs past its shot's last cut (reported, never trimmed)


class Shot(_Model):
    id: UUID
    scene_id: UUID
    number: int = Field(ge=1)
    title: str = ""
    framing: Framing = Framing.MS
    duration_s: int = DEFAULT_SHOT_SECONDS
    start_s: int = 0
    sound_mode: SoundMode = SoundMode.AMBIENT
    camera_link: CameraLink = CameraLink.CUT
    frame_strategy: FrameStrategy = FrameStrategy.GENERATE
    speaker_id: UUID | None = None  # the one visible speaker, when there is one
    beats: list[Beat] = Field(default_factory=list)
    block_start: int = 0  # the script blocks this shot covers: [block_start, block_end)
    block_end: int = 0
    word_target: int = 0
    words: int = 0
    status: ShotStatus = ShotStatus.DRAFT
    version: int = 1

    @field_validator("duration_s")
    @classmethod
    def _renderable(cls, v: int) -> int:
        if v not in VEO_DURATIONS:
            raise ValueError(f"duration_s must be one of {VEO_DURATIONS}")
        return v

    @property
    def code(self) -> str:
        return f"S{self.number:02d}"


class Scene(_Model):
    id: UUID
    episode_id: UUID
    number: int = Field(ge=1)
    heading: str
    title: str = ""
    location_id: UUID | None = None
    time_of_day: str = ""
    envelope_s: int = Field(ge=4)
    script: list[ScriptBlock] = Field(default_factory=list)
    script_version: int = 1
    status: SceneStatus = SceneStatus.DRAFT
    note: str = ""


class Episode(_Model):
    id: UUID
    production_id: UUID
    number: int = Field(ge=1)
    title: str = ""
    synopsis: str = ""
    status: EpisodeStatus = EpisodeStatus.DRAFT
