"""Video generation: what an engine can render, what a person sets, which pictures go in which order, the seed, and the
exact request (plan/2026-11-06c, PLAN.md Q1 answered).

Kept apart from `contracts.veo`, which is Veo TIMING and mirrors the frontend: a prompt engine and a generation engine
are different tables and are never merged. Pure pydantic + stdlib (the `contracts` rule); nothing here calls a network.
Forked from PromptMotion `contracts/media.py` (see `src/services/video_render/UPSTREAM.md`), commit `a027aec`.

Five rules this file keeps, each with a test:
  * ORDER IS THE LIST ORDER. Nothing sorts or de-duplicates references; Omni numbers them by position.
  * ATTACHED == CITED. The citation block is built from the same list that becomes the payload.
  * LABELS ARE WORDS. A code, id, path or hash in a label is drawn by the model as on-screen lettering.
  * CHECKS REPORT, THEY NEVER EDIT. The prose and a person's list are never rewritten to fit.
  * NO DEATH OR VIOLENCE WORDS IN THE DESCRIPTION. A listed word (`contracts.safe_depiction`) blocks the send before
    anything is spent; one in a spoken line is advice only (plan/2026-11-10b).
  * A SEED IS RECORDED. Every take carries the seed it was sent with (when the engine takes one).
  * THE MODEL AND SIZE ARE THE PRODUCTION'S. Chosen when it is created, never by a shot or a press; a draft is always
    `DRAFT_ENGINE` at `DRAFT_RESOLUTION` (the person's decision, 2026-11-06).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts import safe_depiction
from contracts.producer import Check, Pins
from contracts.veo import VEO_DURATIONS, FrameStrategy

Source = Literal["production", "shot", "run", "code", "draft"]
Slot = Literal["first_frame", "last_frame", "reference"]
SeedSupport = Literal["honoured", "accepted", "none"]

SEED_MAX = 2**32 - 1
MAX_TAKES_PER_PRESS = 1  # one video per press of Generate (the person's decision, 2026-11-06)
DEFAULT_ENGINE = "omni_flash"
# A draft is a cheap look before the real take: always Omni Flash at 360p, whatever the production's model (Veo has
# no 360p). The production's own size is chosen from the rest.
DRAFT_ENGINE = "omni_flash"
DRAFT_RESOLUTION = "360p"
DEFAULT_RESOLUTION = "720p"
# Fixed when the production is created; `PATCH /productions/{id}` refuses a change to any of them.
LOCKED_VIDEO_FIELDS = ("engine", "model", "resolution")


def version_problem(engine: str, model: str | None) -> str | None:
    """Why a model a shot or a press picked cannot go with this engine, or None."""
    cap = capability(engine)
    ids = [m for _, m in cap.versions]
    if model is None or model in ids:
        return None
    if not ids:
        return f"{cap.label} has no versions to choose from; its model is the production's."
    return f"{model} is not a version of {cap.label}. Choose {_or_list(tuple(label for label, _ in cap.versions))}."


def final_resolutions(engine: str) -> tuple[str, ...]:
    """The sizes a production on this engine may choose: the engine's, less the draft size."""
    return tuple(r for r in capability(engine).resolutions if r != DRAFT_RESOLUTION)

# Omni names each picture "Image n", n = its position among the image parts (1-based), in plain words. Google's Omni
# page (read 2026-11-18): the `<FIRST_FRAME>` / `<IMAGE_REF_0>` control strings "are deprecated and unsupported in
# future models. Describe how each image or video should be used in natural language instead." (plan/2026-11-18)
IMAGE_TAG = "Image {n}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── engine capabilities (§4.1) ────────────────────────────────────────────────────────────────────────────────


class OptionSpec(_Model):
    """One engine knob beyond the common ones, typed so the panel can draw it and `validate_render` can check it.
    `default` None means "not sent": an option is only ever sent because a person set it."""

    kind: Literal["choice", "bool", "int"]
    label: str
    choices: tuple[str, ...] = ()
    low: int | None = None
    high: int | None = None
    default: str | int | bool | None = None

    def accepts(self, value: object) -> bool:
        if self.kind == "bool":
            return isinstance(value, bool)
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            return (self.low is None or value >= self.low) and (self.high is None or value <= self.high)
        return isinstance(value, str) and value in self.choices


class EngineCapability(_Model):
    key: str
    label: str
    model: str  # default model id; `VIDEO__MODELS` overrides per engine without a code change
    api: Literal["interactions", "predict_long_running"]
    durations: tuple[int, ...]  # what Hiru OFFERS: its ladder ∩ the engine's (4/6/8; 10 s stays off, PLAN.md Q4)
    aspects: tuple[str, ...]
    resolutions: tuple[str, ...]
    max_refs: int  # plain references; frames are not counted
    first_frame: bool
    last_frame: bool
    refs_with_first_frame: bool  # may references and a start frame go in one request (Phase 0 probe)
    refs_with_last_frame: bool = True  # may references and an end frame go in one request
    max_images: int = 0  # every picture in the request, frames included; 0 = only `max_refs` applies
    max_per_person: int = 0  # pictures bound to one canon entity; 0 = no limit
    max_people_with_sheets: int = 0  # Hiru's default attaches sheets for at most this many people; 0 = no limit
    # "one": a person gets one picture (the look sheet, else the base sheet). "face_and_look": the face sheet (else the
    # base sheet), then the look sheet (plan/2026-11-18, lab/omni_refs run 003).
    person_pictures: Literal["one", "face_and_look"] = "one"
    full_length_for: tuple[str, ...] = ()  # Veo: "1080p", "references", "last_frame" need `full_length`
    full_length: int = 0
    seed: SeedSupport  # set by the Phase 0 probe, never assumed
    max_takes_per_call: int = 1  # candidateCount / sampleCount, 1 until probed
    negative_prompt: bool = False
    options: dict[str, OptionSpec] = Field(default_factory=dict)
    verified: bool = False  # True only after one real take on our key (Phase 6)
    notes: str = ""
    # The versions a person may pick for one press, as (label, model id); the first is `model`. Empty: the model is
    # the production's alone (Veo).
    versions: tuple[tuple[str, str], ...] = ()


_VEO_OPTIONS = {
    "person_generation": OptionSpec(kind="choice", label="People in the picture",
                                    choices=("allow_adult", "allow_all", "dont_allow")),
}

# Starting values are PromptMotion's rows (a027aec). The seed rows are the honest unknown: Omni's S0 probe saw `seed`
# accepted on the wrong endpoint, so it stays "none" (not sent) until the probe settles it on /interactions.
# Omni takes a start frame WITH references as `reference_to_video` (plan/2026-11-18, lab/omni_refs run 003: frame + 4
# sheets, the sheet's clothes and face held). As `image_to_video` the same request is a 400 ("Image-to-video does not
# support more than 2 images", 2026-11-06), so the provider picks the task from the pictures. Google's limits for 1.2:
# 6 reference images, at most 3 per character, for up to 2 characters; the start frame is counted in the 6 (safe).
# An end frame with references is not tested and stays apart.
ENGINE_CAPABILITIES: dict[str, EngineCapability] = {
    "omni_flash": EngineCapability(
        key="omni_flash", label="Omni Flash", model="gemini-omni-1.1-flash", api="interactions",
        versions=(("1.1", "gemini-omni-1.1-flash"), ("1.2", "gemini-omni-1.2-flash")),
        durations=VEO_DURATIONS, aspects=("9:16", "16:9"), resolutions=("360p", "720p", "1080p"), max_refs=6,
        first_frame=True, last_frame=True, refs_with_first_frame=True, refs_with_last_frame=False, max_images=6,
        max_per_person=3, max_people_with_sheets=2, person_pictures="face_and_look", seed="none",
        notes="A start frame and up to 5 sheets (at most 3 of one person, sheets for up to 2 people), each named "
              "Image 1, Image 2… in the order sent. An end frame goes without sheets."),
    "veo_3_1": EngineCapability(
        key="veo_3_1", label="Veo 3.1", model="veo-3.1-generate-preview", api="predict_long_running",
        durations=VEO_DURATIONS, aspects=("9:16", "16:9"), resolutions=("720p", "1080p"), max_refs=3,
        first_frame=True, last_frame=True, refs_with_first_frame=False, seed="accepted",
        full_length=8, full_length_for=("1080p", "references", "last_frame"), options=_VEO_OPTIONS,
        notes="1080p, references and an end frame need 8 s."),
    "veo_3_1_fast": EngineCapability(
        key="veo_3_1_fast", label="Veo 3.1 Fast", model="veo-3.1-fast-generate-preview", api="predict_long_running",
        durations=VEO_DURATIONS, aspects=("9:16", "16:9"), resolutions=("720p", "1080p"), max_refs=3,
        first_frame=True, last_frame=True, refs_with_first_frame=False, seed="accepted",
        full_length=8, full_length_for=("1080p", "references", "last_frame"), options=_VEO_OPTIONS,
        notes="Faster Veo 3.1. 1080p, references and an end frame need 8 s."),
}


def capability(engine: str) -> EngineCapability:
    try:
        return ENGINE_CAPABILITIES[engine]
    except KeyError:
        raise ValueError(f"unknown video engine {engine!r}; known: {sorted(ENGINE_CAPABILITIES)}") from None


def seed_note(engine: str) -> str:
    """What the panel says about the seed. Repeatability is never claimed that has not been measured."""
    cap = capability(engine)
    if cap.seed == "none":
        return "This model does not take a seed: every take is new."
    if cap.seed == "accepted":
        return "This model takes a seed, but it is not proven to repeat a take."
    return "This model honours a seed: the same request and seed give the same take."


# ── seed (§4.4) ───────────────────────────────────────────────────────────────────────────────────────────────


class SeedChoice(_Model):
    mode: Literal["random", "fixed", "from_take"] = "random"
    value: int | None = Field(default=None, ge=0, le=SEED_MAX)  # fixed
    take_id: UUID | None = None  # from_take: that take's seed AND its whole spec


Draw = Callable[[int], int]


def draw_seeds(choice: SeedChoice, takes: int, *, take_seed: int | None = None,
               draw: Draw = secrets.randbelow) -> list[int]:
    """One seed per take, decided BEFORE dispatch so even a random take can be made again.

    `random`: a fresh draw each. `fixed`: value, value+1, ... (one seed for all would give near-identical takes).
    `from_take`: that take's seed, then +1 for each further take."""
    if choice.mode == "random":
        return [draw(SEED_MAX + 1) for _ in range(takes)]
    base = choice.value if choice.mode == "fixed" else take_seed
    if base is None:
        raise ValueError("a seed taken from a take needs that take's seed" if choice.mode == "from_take"
                         else "a fixed seed needs a value")
    return [base + i for i in range(takes)]


def seed_phrase(seeds: Sequence[int]) -> str:
    return "seed " + str(seeds[0]) if len(seeds) == 1 else "seeds " + ", ".join(str(s) for s in seeds)


# ── settings, in three layers (§4.2) ──────────────────────────────────────────────────────────────────────────

_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
OptionValue = str | int | bool


def _model_id(v: str | None) -> str | None:
    if v is not None and not _MODEL_ID.match(v):
        raise ValueError("a model id is letters, digits, dots, dashes and underscores")
    return v


class VideoSettings(_Model):
    """The production's (`ProductionSettings.video`): every field has a value. `engine`, `model` and `resolution` are
    set when the production is created and never change (`LOCKED_VIDEO_FIELDS`)."""

    engine: str = DEFAULT_ENGINE
    model: str | None = None  # a specific model id, e.g. a newer Veo preview
    resolution: str = DEFAULT_RESOLUTION
    aspect_ratio: str | None = None  # None → the production's orientation
    duration_s: int | None = None  # None → the shot's length
    takes: int = Field(default=1, ge=1, le=MAX_TAKES_PER_PRESS)
    seed: SeedChoice = Field(default_factory=lambda: SeedChoice())
    negative_prompt: str = Field(default="", max_length=2000)
    options: dict[str, OptionValue] = Field(default_factory=dict)

    _check_model = field_validator("model")(lambda cls, v: _model_id(v))

    @model_validator(mode="after")
    def _engine_and_size(self) -> VideoSettings:
        sizes = final_resolutions(self.engine)  # raises for an unknown engine
        if self.resolution not in sizes:
            raise ValueError(f"{self.resolution} is not a size for {capability(self.engine).label}; "
                             f"choose {_or_list(sizes)} ({DRAFT_RESOLUTION} is for drafts)")
        return self


class VideoOverrides(_Model):
    """A shot's or a run's one-off overrides: only the fields set are used. The engine and size are not here: they are
    the production's (`LOCKED_VIDEO_FIELDS`), so a shot or a press that names one is refused. `model` is one of the
    engine's `versions` (Omni Flash 1.1 / 1.2); any other is a blocking check, never a silent swap."""

    model: str | None = None
    aspect_ratio: str | None = None
    duration_s: int | None = None
    takes: int | None = Field(default=None, ge=1, le=MAX_TAKES_PER_PRESS)
    seed: SeedChoice | None = None
    negative_prompt: str | None = Field(default=None, max_length=2000)
    options: dict[str, OptionValue] = Field(default_factory=dict)

    _check_model = field_validator("model")(lambda cls, v: _model_id(v))


class ResolvedSettings(_Model):
    engine: str
    model: str | None
    resolution: str
    aspect_ratio: str
    duration_s: int
    takes: int
    seed: SeedChoice
    negative_prompt: str
    options: dict[str, OptionValue]
    sources: dict[str, Source]  # field → where its value came from; options as "options.<key>"
    draft: bool = False


def resolve(production: VideoSettings, shot: VideoOverrides | None, run: VideoOverrides | None, *,
            production_aspect: str, shot_seconds: int, draft: bool = False) -> ResolvedSettings:
    """Merge production → shot → run, field by field, and say where each value came from. Code never moves a
    person's value: one the chosen engine cannot take is a blocking check in `validate_render`, not a silent snap.

    The size comes from the production alone; the model too, unless the shot or the press picks a version (it is
    applied after the draft's engine, so a draft takes it as well). A `draft` is `DRAFT_ENGINE` at `DRAFT_RESOLUTION`;
    when that is another engine than the production's, the production's negative prompt and engine options are not
    carried over (they belong to its own engine)."""
    layers: list[tuple[Source, Any]] = [("production", production)]
    if shot is not None:
        layers.append(("shot", shot))
    if run is not None:
        layers.append(("run", run))
    values: dict[str, Any] = {"engine": production.engine, "model": production.model,
                              "resolution": production.resolution}
    sources: dict[str, Source] = {"engine": "production", "model": "production" if production.model else "code",
                                  "resolution": "production"}
    for name in ("aspect_ratio", "duration_s", "takes", "seed", "negative_prompt"):
        for src, lay in layers:
            v = getattr(lay, name)
            if v is not None:
                values[name], sources[name] = v, src
    options: dict[str, OptionValue] = {}
    for src, lay in layers:
        for k, v in lay.options.items():
            options[k] = v
            sources[f"options.{k}"] = src
    if values.get("aspect_ratio") is None:
        values["aspect_ratio"], sources["aspect_ratio"] = production_aspect, "production"
    if values.get("duration_s") is None:
        values["duration_s"], sources["duration_s"] = shot_seconds, "code"
    if draft:
        if production.engine != DRAFT_ENGINE:
            values["model"], sources["model"] = None, "draft"
            values["negative_prompt"], options = "", {}
            sources = {k: v for k, v in sources.items() if not k.startswith("options.")}
            sources["negative_prompt"] = "draft"
        values["engine"], values["resolution"] = DRAFT_ENGINE, DRAFT_RESOLUTION
        sources["engine"] = sources["resolution"] = "draft"
    for src, lay in layers[1:]:
        if lay.model is not None:
            values["model"], sources["model"] = lay.model, src
    return ResolvedSettings(options=options, sources=sources, draft=draft, **values)


# ── references: binding and order (§4.3) ──────────────────────────────────────────────────────────────────────

# `face_sheet`: a card's face asset (several angles of one face); `canon_sheet`: its other sheets (plan/2026-11-18).
RefKind = Literal["accepted_frame", "carried_frame", "canon_sheet", "face_sheet", "look_sheet", "take_last_frame",
                  "upload"]
Bucket = Literal["frames", "references", "takes"]


class RefSource(_Model):
    kind: RefKind
    id: UUID  # first_frames / canon_versions / canon_looks / takes / an uploaded file
    path: str  # private bucket path; never a URL, never sent to a browser
    bucket: Bucket
    sha256: str = ""  # recorded at send time: proves which picture went
    version: int | None = None  # a canon card's version when the picture was chosen


class RefBinding(_Model):
    slot: Slot
    source: RefSource
    binds_to: UUID | None = None  # the canon entity this picture IS (character, place, prop)
    label: str  # plain words the prompt uses: "the character sheet for Nimal"
    origin: Literal["code", "person"] = "code"

    @field_validator("label")
    @classmethod
    def _trim(cls, v: str) -> str:
        return " ".join(v.split())


class ShotVideoState(_Model):
    """`shots.video_settings`: the shot's overrides AND its reference list once a person has touched it."""

    settings: VideoOverrides = Field(default_factory=lambda: VideoOverrides())
    references: list[RefBinding] | None = None  # None → Hiru's choice (`default_references`)
    uploads: list[RefSource] = Field(default_factory=list)  # pictures a person added for this shot


_CANON_CODE = re.compile(r"\b[A-Za-z]{1,3}-?\d{1,4}\b")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HASHY = re.compile(r"\b(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{12,}\b|\b[0-9a-f]{8,}\b")
_PATHY = re.compile(r"[/\\]|\.\w{2,4}\b|^[a-z]+://", re.IGNORECASE)


def label_problem(label: str) -> str | None:
    """Why this label may not go in a prompt, or None. A model draws a code, id, path or hash as on-screen
    lettering, so a label is words only."""
    text = label.strip()
    if not text:
        return "A picture needs a label in plain words (e.g. the character sheet for Nimal)."
    if len(text) > 120:
        return "A label is a short phrase (at most 120 characters)."
    if _UUID.search(text) or _HASHY.search(text):
        return f"“{text}” looks like an id or a hash; the model would draw it as lettering. Use a name."
    if _CANON_CODE.search(text):
        return f"“{text}” contains a code like C01; the model would draw it as lettering. Use the name instead."
    if _PATHY.search(text):
        return f"“{text}” looks like a file path or a link. Use plain words."
    return None


@dataclass(frozen=True)
class SheetCandidate:
    """One canon entity of the shot, as the frame rule offers it: `seen` is whether the camera sees it (a person only
    heard is never attached), `sheet` its base sheet, `face` its face sheet and `look_sheet` the look the scene uses,
    when there are."""

    entity_id: UUID
    kind: Literal["character", "location", "prop"]
    name: str
    seen: bool
    sheet: RefSource | None = None
    look_sheet: RefSource | None = None
    face: RefSource | None = None


@dataclass
class DefaultReferences:
    bindings: list[RefBinding]
    left_out: list[str] = field(default_factory=list)  # plain words, shown on the panel; never dropped silently


_KIND_RANK = {"character": 0, "location": 1, "prop": 2}
_SHEET_WORDS = {"character": "the character sheet for", "location": "the location plate for",
                "prop": "the reference sheet for"}


def _pictures_of(cap: EngineCapability, c: SheetCandidate) -> list[tuple[RefSource, str]]:
    """The pictures one entity brings, with their words. A person on an engine that takes `face_and_look` brings the
    face sheet (else the base sheet), then the look sheet (else the base sheet when the face sheet stood first)."""
    def word(src: RefSource) -> str:
        if src.kind == "look_sheet":
            return f"the look sheet for {c.name}"
        if src.kind == "face_sheet":
            return f"the face sheet for {c.name}"
        return f"{_SHEET_WORDS[c.kind]} {c.name}"

    if c.kind == "character" and cap.person_pictures == "face_and_look":
        first = c.face or c.sheet
        second = c.look_sheet or (c.sheet if c.face is not None else None)
        picks = [p for p in (first, second) if p is not None]
    else:
        pick = c.look_sheet or c.sheet
        picks = [pick] if pick is not None else []
    return [(p, word(p)) for p in picks]


def default_references(*, cap: EngineCapability, strategy: FrameStrategy, accepted_frame: RefSource | None,
                       carried_frame: RefSource | None, candidates: Iterable[SheetCandidate]) -> DefaultReferences:
    """Hiru's choice of pictures, by the same rule as frames (`frame_render` `FrameJob.references`):
    the start frame (the accepted one, else the last frame carried from the shot before when this shot carries on),
    then the sheets of the people the camera SEES (`_pictures_of`), then the place, then props. Cut to the engine's
    caps; what was cut is listed. Someone only heard is never attached.

    An engine that takes a start frame OR reference pictures, not both (`refs_with_first_frame` False), keeps the start
    frame and lists the sheets. One that takes both (Omni, plan/2026-11-18) leaves places and props out when there is a
    start frame (the frame already shows them) and attaches sheets for at most `max_people_with_sheets` people."""
    out: list[RefBinding] = []
    left: list[str] = []
    start = accepted_frame or (carried_frame if strategy is FrameStrategy.CARRY_LAST_FRAME else None)
    if start is not None and cap.first_frame:
        words = "the opening frame" if start.kind == "accepted_frame" else "the last frame of the shot before"
        out.append(RefBinding(slot="first_frame", source=start, label=words, origin="code"))
    ordered = sorted(candidates, key=lambda c: _KIND_RANK[c.kind])  # stable: the frame rule's order inside a kind
    # An engine that takes a start frame OR reference pictures, not both, keeps the start frame (it was painted from the
    # same sheets, so the faces are already in it) and says what it left out.
    has_start = bool(out)
    exclusive = has_start and not cap.refs_with_first_frame
    room = cap.max_refs
    if cap.max_images:
        room = min(room, cap.max_images - len(out))
    people = 0
    for c in ordered:
        if not c.seen:
            continue
        picks = _pictures_of(cap, c)
        if not picks:
            continue
        if exclusive:
            left += [f"{w} ({cap.label} takes a start frame or reference pictures, not both)" for _, w in picks]
            continue
        if has_start and c.kind != "character" and cap.refs_with_first_frame:
            left += [f"{w} (the start frame already shows it)" for _, w in picks]
            continue
        if c.kind == "character" and cap.max_people_with_sheets and people >= cap.max_people_with_sheets:
            left += [f"{w} ({cap.label} keeps faces for up to {cap.max_people_with_sheets} people)" for _, w in picks]
            continue
        if cap.max_per_person:
            picks, cut = picks[:cap.max_per_person], picks[cap.max_per_person:]
            left += [w for _, w in cut]
        took = False
        for pick, w in picks:
            if room <= 0:
                left.append(w)
                continue
            out.append(RefBinding(slot="reference", source=pick, binds_to=c.entity_id, label=w, origin="code"))
            room -= 1
            took = True
        people += 1 if took and c.kind == "character" else 0
    return DefaultReferences(out, left)


def asset_id(owner: UUID | str, path: str) -> UUID:
    """A stable id for one picture of a card, a look or an upload: the same picture always has the same id, so a saved
    list and the picker agree without a browser ever holding a path."""
    return uuid5(NAMESPACE_URL, f"hiru:asset:{owner}:{path}")


def references_of(bindings: Sequence[RefBinding]) -> list[RefBinding]:
    """The plain references, in the list's order. Nothing sorts or de-duplicates them."""
    return [b for b in bindings if b.slot == "reference"]


def frame_of(bindings: Sequence[RefBinding], slot: Slot) -> RefBinding | None:
    return next((b for b in bindings if b.slot == slot), None)


def wire_order(bindings: Sequence[RefBinding]) -> list[RefBinding]:
    """The start frame, then the references in the person's order, then the end frame: the fixed layout that makes
    Omni's "Image n" the n-th image part of the request, with the opening frame always Image 1 (plan/2026-11-18).
    Veo routes each picture by its slot, so the layout changes nothing there."""
    first, last = frame_of(bindings, "first_frame"), frame_of(bindings, "last_frame")
    return [*([first] if first else []), *references_of(bindings), *([last] if last else [])]


MAX_REFERENCE_BYTES = 15 * 1024 * 1024  # the `references` bucket's limit


def image_kind(data: bytes) -> tuple[str, str] | None:
    """(extension, mime) by content: PNG, JPEG or WebP. What a person may add as a reference picture."""
    if data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]):
        return "png", "image/png"
    if data[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return "jpg", "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


# ── the request (§4.5) ────────────────────────────────────────────────────────────────────────────────────────


class RenderSpec(_Model):
    """ONE take's resolved request, exactly as sent (no image bytes). `prose` is the video prompt as written;
    the citation block is built from `references` by the adapter, never stored apart from them."""

    engine: str
    model: str
    prose: str
    references: list[RefBinding] = Field(default_factory=list)
    resolution: str
    aspect_ratio: str
    duration_s: int
    negative_prompt: str = ""
    options: dict[str, OptionValue] = Field(default_factory=dict)
    seed: int | None = None
    prompt_id: UUID | None = None
    prompt_version: int | None = None
    frame_id: UUID | None = None
    pins: Pins | None = None
    draft: bool = False  # a quick look at `DRAFT_RESOLUTION`, not the production's take


def spec_for(settings: ResolvedSettings, *, prose: str, references: Sequence[RefBinding], seed: int | None = None,
             prompt_id: UUID | None = None, prompt_version: int | None = None, frame_id: UUID | None = None,
             pins: Pins | None = None) -> RenderSpec:
    cap = capability(settings.engine)
    return RenderSpec(engine=settings.engine, model=settings.model or cap.model, prose=prose,
                      references=list(references), resolution=settings.resolution, aspect_ratio=settings.aspect_ratio,
                      duration_s=settings.duration_s, negative_prompt=settings.negative_prompt,
                      options=dict(settings.options), seed=seed if cap.seed != "none" else None,
                      prompt_id=prompt_id, prompt_version=prompt_version, frame_id=frame_id, pins=pins,
                      draft=settings.draft)


def _config(spec: RenderSpec) -> dict[str, Any]:
    cap = capability(spec.engine)
    config: dict[str, Any] = {"duration_seconds": spec.duration_s, "aspect_ratio": spec.aspect_ratio,
                              "resolution": spec.resolution}
    if cap.seed != "none" and spec.seed is not None:
        config["seed"] = spec.seed
    if cap.negative_prompt and spec.negative_prompt.strip():
        config["negative_prompt"] = spec.negative_prompt.strip()
    for key, value in spec.options.items():
        if key in cap.options:
            config[key] = value
    return config


def _part(binding: RefBinding, tag: str) -> dict[str, Any]:
    return {"tag": tag, "slot": binding.slot, "bucket": binding.source.bucket, "path": binding.source.path,
            "source_id": str(binding.source.id)}


# The words Omni is given for each picture, by what it is (plan/2026-11-18; the wording lab/omni_refs run 003 tested).
# `{tag}` is "Image n", `{label}` the binding's own words. Kept here, in one place, and added by code AFTER the prose,
# so the prompt writer never rewords them.
OMNI_CITATION_HEAD = "Reference images, in the order attached:"
OMNI_LINES: dict[str, str] = {
    "first_frame": ("{tag} is the opening frame of this shot{also}. The video starts exactly on this picture: the same "
                    "framing, people, place, weather and light, and everything that happens grows out of it."),
    "last_frame": "{tag} is the closing frame of this shot{also}. The video ends exactly on this picture.",
    "face_sheet": ("{tag} is {label}: several angles of the same face. That person's face, age, skin tone and hair "
                   "come only from this sheet, at every angle and expression, including when they turn or move closer "
                   "to the camera."),
    "look_sheet": ("{tag} is {label}: exactly what that person wears in this shot, head to toe. When more of them "
                   "comes into view, the clothes, shoes and things they carry match this sheet exactly."),
    "reference": "{tag} is {label}. Keep what it shows exactly.",
}
# Opens with "Never", not "Image n is", so `cited` counts one sentence per picture.
OMNI_CITATION_TAIL = ("Never show {tags} in the video: {they} {are} {refs} only, so no sheet, grey backdrop or panel "
                      "appears and the video never cuts to {them}. Where the words above describe someone's clothes or "
                      "face differently from these pictures, the pictures win.")
_FRAME_WORDS = ("the opening frame", "the closing frame")


def _and_list(values: Sequence[str]) -> str:
    return values[0] if len(values) == 1 else f"{', '.join(values[:-1])} and {values[-1]}"


def _omni_line(b: RefBinding, tag: str) -> str:
    if b.slot in ("first_frame", "last_frame"):
        also = "" if b.label in _FRAME_WORDS else f" ({b.label})"
        return OMNI_LINES[b.slot].format(tag=tag, also=also)
    template = OMNI_LINES.get(b.source.kind) or OMNI_LINES["reference"]
    return template.format(tag=tag, label=b.label)


def build_omni_input(spec: RenderSpec) -> dict[str, Any]:
    """Spec → the Omni request, with every picture CITED. An attached picture the prompt never names drifts the
    frame, so the citation block is built from the same list as the payload: the n-th picture sent is "Image n" and
    its sentence says what it is for. The start frame is always Image 1 (`wire_order`)."""
    parts = [spec.prose.strip()]
    payload: list[dict[str, Any]] = []
    lines: list[str] = []
    sheets: list[str] = []
    for n, b in enumerate(wire_order(spec.references), start=1):
        tag = IMAGE_TAG.format(n=n)
        payload.append(_part(b, tag))
        lines.append(_omni_line(b, tag))
        if b.slot == "reference":
            sheets.append(tag)
    if sheets:
        tags = f"Images {_and_list([s.removeprefix('Image ') for s in sheets])}" if len(sheets) > 1 else sheets[0]
        many = len(sheets) > 1
        lines.append(OMNI_CITATION_TAIL.format(tags=tags, they="they" if many else "it", are="are" if many else "is",
                                               refs="references" if many else "a reference",
                                               them="them" if many else "it"))
    if lines:
        parts.append(OMNI_CITATION_HEAD + "\n" + "\n".join(lines))
    return {"model": spec.model, "prompt": "\n\n".join(p for p in parts if p), "references": payload,
            "config": _config(spec)}


def build_veo_input(spec: RenderSpec) -> dict[str, Any]:
    """Spec → the Veo request pieces. Veo has separate `image` / `lastFrame` / `referenceImages` slots, so the
    provider module reads each part's `slot`; the references are still NAMED in the prompt, by position."""
    plain = references_of(spec.references)
    parts = [spec.prose.strip()]
    if plain:
        parts.append("Reference images, in order: " + "; ".join(
            f"image {i + 1} is {b.label}" for i, b in enumerate(plain)) + ".")
    return {"model": spec.model, "prompt": "\n\n".join(p for p in parts if p),
            "references": [_part(b, "") for b in wire_order(spec.references)], "config": _config(spec)}


ADAPTERS: dict[str, Callable[[RenderSpec], dict[str, Any]]] = {
    "omni_flash": build_omni_input,
    "veo_3_1": build_veo_input,
    "veo_3_1_fast": build_veo_input,
}


def build_request(spec: RenderSpec) -> dict[str, Any]:
    try:
        return ADAPTERS[spec.engine](spec)
    except KeyError:
        raise ValueError(f"no adapter for video engine {spec.engine!r}") from None


def cited(built: Mapping[str, Any]) -> list[str]:
    """The pictures the built prompt cites, one per sentence that opens with "Image n", in the order they appear.
    Omni only (Veo cites by position)."""
    head = OMNI_CITATION_HEAD + "\n"
    block = built["prompt"].split(head)[-1] if head in built["prompt"] else ""
    return re.findall(r"^(Image \d+) is ", block, flags=re.MULTILINE)


def tags_of(spec: RenderSpec) -> list[str]:
    """The name each picture goes by in the request, in wire order: `Image 1`, `Image 2`… for Omni (frames included),
    `image 1` for Veo's references and "start frame" / "end frame" for its frames. What the panel shows beside each
    card, so a person sees the numbers change on a reorder."""
    if capability(spec.engine).api == "interactions":
        return [IMAGE_TAG.format(n=n) for n in range(1, len(wire_order(spec.references)) + 1)]
    out: list[str] = []
    n = 0
    for b in wire_order(spec.references):
        if b.slot == "first_frame":
            out.append("start frame")
        elif b.slot == "last_frame":
            out.append("end frame")
        else:
            n += 1
            out.append(f"image {n}")
    return out


def describe_spec(spec: RenderSpec) -> str:
    """The settings in words, for a take's card: "Omni Flash 1.2 · 720p · 16:9 · 8 s · 3 pictures · seed 1234"."""
    try:
        cap = capability(spec.engine)
        label = cap.label
        version = next((v for v, m in cap.versions if m == spec.model), "")
        if version:
            label = f"{label} {version}"
    except ValueError:
        label = spec.engine
    parts = [label, spec.resolution, spec.aspect_ratio, f"{spec.duration_s} s"]
    if spec.draft:
        parts.insert(0, "Draft")
    if spec.references:
        parts.append(f"{len(spec.references)} picture{'s' if len(spec.references) != 1 else ''}")
    if spec.seed is not None:
        parts.append(f"seed {spec.seed}")
    return " · ".join(parts)


def request_hash(spec: RenderSpec, *, with_seed: bool = True) -> str:
    """The identity of "the same request": the built prompt, the pictures in order (by source, not by bytes), the
    model and every setting. The preview compares it WITHOUT the seed (drawn at send); `Make again` keeps it."""
    built = build_request(spec)
    config = dict(built["config"])
    if not with_seed:
        config.pop("seed", None)
    body = {"engine": spec.engine, "model": built["model"], "prompt": built["prompt"], "config": config,
            "draft": spec.draft,
            "references": [[p["tag"], p["slot"], p["bucket"], p["path"], p["source_id"]] for p in built["references"]]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ── validation (blocking) and checks (§4.2, §4.3) ─────────────────────────────────────────────────────────────


def _fail(label: str) -> Check:
    return Check(label=label, tone="fail")


def _advisory(label: str) -> Check:
    return Check(label=label, tone="advisory")


def _or_list(values: Iterable[str]) -> str:
    vals = list(values)
    return " or ".join(vals) if len(vals) <= 2 else f"{', '.join(vals[:-1])} or {vals[-1]}"


def _full_length_reasons(cap: EngineCapability, spec: RenderSpec) -> list[str]:
    present = {"1080p": spec.resolution == "1080p", "references": bool(references_of(spec.references)),
               "last_frame": frame_of(spec.references, "last_frame") is not None}
    words = {"1080p": "1080p", "references": "reference images", "last_frame": "an end frame"}
    return [words[k] for k in cap.full_length_for if present.get(k)]


def validate_render(spec: RenderSpec, *, seed_choice: SeedChoice | None = None, takes: int = 1) -> list[Check]:
    """Every reason this request cannot be sent, as blocking checks in plain words. Empty means go. Nothing is
    snapped: a value the engine cannot take is reported with the fix, never moved."""
    try:
        cap = capability(spec.engine)
    except ValueError as exc:
        return [_fail(str(exc))]
    out: list[Check] = []
    if not spec.prose.strip():
        out.append(_fail("There is no video prompt for this shot yet."))
    # The prose only: a negative prompt that says "blood" is how a person keeps it OUT (plan/2026-11-10b).
    out += [_fail(safe_depiction.video_label(f)) for f in safe_depiction.blocking(spec.prose)]
    if spec.aspect_ratio not in cap.aspects:
        out.append(_fail(f"{spec.aspect_ratio} is not available on {cap.label}; it renders {_or_list(cap.aspects)}."))
    if spec.resolution not in cap.resolutions:
        out.append(_fail(f"{spec.resolution} is not available on {cap.label}; it renders {_or_list(cap.resolutions)}."))
    if spec.duration_s not in cap.durations:
        out.append(_fail(f"{spec.duration_s} s cannot be rendered on {cap.label}; it makes "
                         f"{'/'.join(str(d) for d in cap.durations)} s clips."))
    reasons = _full_length_reasons(cap, spec)
    if reasons and cap.full_length and spec.duration_s != cap.full_length:
        out.append(_fail(f"{cap.label} takes {', '.join(reasons)} only at {cap.full_length} s; this shot is "
                         f"{spec.duration_s} s."))

    plain, first, last = references_of(spec.references), frame_of(spec.references, "first_frame"), \
        frame_of(spec.references, "last_frame")
    if sum(1 for b in spec.references if b.slot == "first_frame") > 1:
        out.append(_fail("Only one picture can be the start frame."))
    if sum(1 for b in spec.references if b.slot == "last_frame") > 1:
        out.append(_fail("Only one picture can be the end frame."))
    if len(plain) > cap.max_refs:
        out.append(_fail(f"{len(plain)} reference pictures; {cap.label} takes at most {cap.max_refs}. "
                         f"Remove {len(plain) - cap.max_refs}."))
    elif cap.max_images and len(spec.references) > cap.max_images:
        out.append(_fail(f"{len(spec.references)} pictures; {cap.label} takes at most {cap.max_images}, the start "
                         f"frame included. Remove {len(spec.references) - cap.max_images}."))
    if first is not None and not cap.first_frame:
        out.append(_fail(f"{cap.label} cannot start from a picture."))
    if last is not None and not cap.last_frame:
        out.append(_fail(f"{cap.label} cannot aim at an end frame."))
    if plain and first is not None and not cap.refs_with_first_frame:
        out.append(_fail(f"{cap.label} takes either reference pictures or a start frame, not both."))
    if plain and last is not None and not cap.refs_with_last_frame:
        out.append(_fail(f"{cap.label} takes either reference pictures or an end frame, not both."))
    if cap.max_per_person:
        per: dict[UUID, int] = {}
        for b in plain:
            if b.binds_to is not None:
                per[b.binds_to] = per.get(b.binds_to, 0) + 1
        if any(n > cap.max_per_person for n in per.values()):
            out.append(_fail(f"{cap.label} takes at most {cap.max_per_person} pictures of one person or thing. "
                             f"Remove some from the one that has {max(per.values())}."))
    for b in spec.references:
        problem = label_problem(b.label)
        if problem:
            out.append(_fail(problem))
        if not b.source.path.strip():
            out.append(_fail(f"“{b.label}” has no picture file."))

    if spec.negative_prompt.strip() and not cap.negative_prompt:
        out.append(_fail(f"{cap.label} does not take a negative prompt. Clear it or choose another model."))
    for key, value in spec.options.items():
        opt = cap.options.get(key)
        if opt is None:
            out.append(_fail(f"{cap.label} has no setting called “{key}”."))
        elif not opt.accepts(value):
            out.append(_fail(f"“{value}” is not a choice for {opt.label} on {cap.label}."))
    if seed_choice is not None:
        if seed_choice.mode == "fixed" and seed_choice.value is None:
            out.append(_fail("A fixed seed needs a number."))
        elif seed_choice.mode == "fixed" and seed_choice.value is not None and seed_choice.value + takes - 1 > SEED_MAX:
            out.append(_fail(f"A fixed seed plus {takes} takes goes past {SEED_MAX}."))
        if seed_choice.mode == "fixed" and cap.seed == "none":
            out.append(_fail(seed_note(spec.engine) + " Choose Random."))
    return out


@dataclass(frozen=True)
class RenderFacts:
    """What `check_render` needs that the request itself does not carry; the API builds it from trusted data."""

    seen: Mapping[UUID, str] = field(default_factory=dict)  # people the camera sees: id → name
    names: Mapping[UUID, str] = field(default_factory=dict)  # every canon entity of the shot: id → name
    current_versions: Mapping[UUID, int] = field(default_factory=dict)  # canon entity id → current card version
    frame_stale: Sequence[str] = ()  # `stale_reasons` for the start frame, in words


def _named(prose: str, name: str) -> bool:
    name = name.strip()
    return bool(name) and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", prose, re.IGNORECASE) is not None


def check_render(spec: RenderSpec, facts: RenderFacts) -> list[Check]:
    """Advisory checks on the bound request. Report only: the prose and the list are never edited to fit."""
    out: list[Check] = [_advisory(safe_depiction.spoken_label(f)) for f in safe_depiction.scan(spec.prose)
                        if f.spoken]
    try:
        cap: EngineCapability | None = capability(spec.engine)
    except ValueError:
        cap = None
    # Each reference's number as the request names it: its place among ALL pictures on Omni (the frame is Image 1),
    # among the references on Veo.
    every = cap is not None and cap.api == "interactions"
    numbered = [(n, b) for n, b in enumerate(wire_order(spec.references), start=1) if b.slot == "reference"] if every \
        else list(enumerate(references_of(spec.references), start=1))
    bound: dict[UUID, int] = {}
    for n, b in numbered:
        if b.binds_to is None:
            continue
        bound[b.binds_to] = bound.get(b.binds_to, 0) + 1
        name = facts.names.get(b.binds_to) or facts.seen.get(b.binds_to) or ""
        if name and not _named(spec.prose, name):
            out.append(_advisory(f"Image {n} is {name}; the prompt never mentions them. "
                                 "The picture will drift the frame."))
        have, now = b.source.version, facts.current_versions.get(b.binds_to)
        if have is not None and now is not None and have < now:
            out.append(_advisory(f"The picture of {name or b.label} is from an older card (v{have}; now v{now})."))
    if cap is None or cap.person_pictures == "one":  # a face + a look sheet per person is the rule on the others
        for who, n in bound.items():
            if n > 1:
                out.append(_advisory(f"{facts.names.get(who, 'Someone')} has {n} reference pictures."))
    people = [who for who in bound if who in facts.seen]
    if cap is not None and cap.max_people_with_sheets and len(people) > cap.max_people_with_sheets:
        names = _and_list([facts.seen[w] for w in people])
        out.append(_advisory(f"{names} all have pictures; {cap.label} keeps faces for up to "
                             f"{cap.max_people_with_sheets} people, so some faces may drift."))
    for who, name in facts.seen.items():
        if who not in bound:
            out.append(_advisory(f"{name} is in the shot but has no reference picture."))
    for reason in facts.frame_stale:
        if frame_of(spec.references, "first_frame") is not None:
            out.append(_advisory(f"The start frame is out of date: {reason}."))
    return out
