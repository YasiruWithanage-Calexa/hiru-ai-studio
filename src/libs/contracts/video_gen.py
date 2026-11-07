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


def final_resolutions(engine: str) -> tuple[str, ...]:
    """The sizes a production on this engine may choose: the engine's, less the draft size."""
    return tuple(r for r in capability(engine).resolutions if r != DRAFT_RESOLUTION)

REF_TAG = "<IMAGE_REF_{n}>"
FIRST_FRAME_TAG = "<FIRST_FRAME>"
LAST_FRAME_TAG = "<LAST_FRAME>"


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
    full_length_for: tuple[str, ...] = ()  # Veo: "1080p", "references", "last_frame" need `full_length`
    full_length: int = 0
    seed: SeedSupport  # set by the Phase 0 probe, never assumed
    max_takes_per_call: int = 1  # candidateCount / sampleCount, 1 until probed
    negative_prompt: bool = False
    options: dict[str, OptionSpec] = Field(default_factory=dict)
    verified: bool = False  # True only after one real take on our key (Phase 6)
    notes: str = ""


_VEO_OPTIONS = {
    "person_generation": OptionSpec(kind="choice", label="People in the picture",
                                    choices=("allow_adult", "allow_all", "dont_allow")),
}

# Starting values are PromptMotion's rows (a027aec). The seed rows are the honest unknown: Omni's S0 probe saw `seed`
# accepted on the wrong endpoint, so it stays "none" (not sent) until the probe settles it on /interactions.
# Omni does NOT take references with a start frame: a request with a frame is image-to-video, and the live endpoint
# answered a start frame + three sheets with 400 "Image-to-video does not support more than 2 images." (2026-11-06).
ENGINE_CAPABILITIES: dict[str, EngineCapability] = {
    "omni_flash": EngineCapability(
        key="omni_flash", label="Omni Flash", model="gemini-omni-1.1-flash", api="interactions",
        durations=VEO_DURATIONS, aspects=("9:16", "16:9"), resolutions=("360p", "720p", "1080p"), max_refs=10,
        first_frame=True, last_frame=True, refs_with_first_frame=False, seed="none",
        notes="A start frame (and an end frame) OR up to 10 reference pictures cited as <IMAGE_REF_n>, not both."),
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
    """A shot's or a run's one-off overrides: only the fields set are used. The model and size are not here: they are
    the production's (`LOCKED_VIDEO_FIELDS`), so a shot or a press that names one is refused."""

    aspect_ratio: str | None = None
    duration_s: int | None = None
    takes: int | None = Field(default=None, ge=1, le=MAX_TAKES_PER_PRESS)
    seed: SeedChoice | None = None
    negative_prompt: str | None = Field(default=None, max_length=2000)
    options: dict[str, OptionValue] = Field(default_factory=dict)


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

    The model and size come from the production alone. A `draft` is `DRAFT_ENGINE` at `DRAFT_RESOLUTION`; when that is
    another engine than the production's, the production's negative prompt and engine options are not carried over
    (they belong to its own engine)."""
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
    return ResolvedSettings(options=options, sources=sources, draft=draft, **values)


# ── references: binding and order (§4.3) ──────────────────────────────────────────────────────────────────────

RefKind = Literal["accepted_frame", "carried_frame", "canon_sheet", "look_sheet", "take_last_frame", "upload"]
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
    heard is never attached), `sheet` its base sheet and `look_sheet` the look the scene uses, when there is one."""

    entity_id: UUID
    kind: Literal["character", "location", "prop"]
    name: str
    seen: bool
    sheet: RefSource | None = None
    look_sheet: RefSource | None = None


@dataclass
class DefaultReferences:
    bindings: list[RefBinding]
    left_out: list[str] = field(default_factory=list)  # plain words, shown on the panel; never dropped silently


_KIND_RANK = {"character": 0, "location": 1, "prop": 2}
_SHEET_WORDS = {"character": "the character sheet for", "location": "the location plate for",
                "prop": "the reference sheet for"}


def default_references(*, cap: EngineCapability, strategy: FrameStrategy, accepted_frame: RefSource | None,
                       carried_frame: RefSource | None, candidates: Iterable[SheetCandidate]) -> DefaultReferences:
    """Hiru's choice of pictures, by the same rule as frames (`frame_render` `FrameJob.references`):
    the start frame (the accepted one, else the last frame carried from the shot before when this shot carries on),
    then the sheets of the people the camera SEES (a look sheet before the base sheet), then the place, then props.
    Cut to the engine's cap; what was cut is listed. Someone only heard is never attached. An engine that takes a start
    frame or references but not both (`refs_with_first_frame` False) keeps the start frame and lists the sheets."""
    out: list[RefBinding] = []
    left: list[str] = []
    start = accepted_frame or (carried_frame if strategy is FrameStrategy.CARRY_LAST_FRAME else None)
    if start is not None and cap.first_frame:
        words = "the opening frame" if start.kind == "accepted_frame" else "the last frame of the shot before"
        out.append(RefBinding(slot="first_frame", source=start, label=words, origin="code"))
    ordered = sorted(candidates, key=lambda c: _KIND_RANK[c.kind])  # stable: the frame rule's order inside a kind
    # An engine that takes a start frame OR reference pictures, not both, keeps the start frame (it was painted from the
    # same sheets, so the faces are already in it) and says what it left out.
    exclusive = bool(out) and not cap.refs_with_first_frame
    attached = 0
    for c in ordered:
        if not c.seen:
            continue
        pick = c.look_sheet or c.sheet
        if pick is None:
            continue
        word = f"the look sheet for {c.name}" if pick.kind == "look_sheet" else f"{_SHEET_WORDS[c.kind]} {c.name}"
        if exclusive:
            left.append(f"{word} ({cap.label} takes a start frame or reference pictures, not both)")
            continue
        if attached >= cap.max_refs:
            left.append(word)
            continue
        out.append(RefBinding(slot="reference", source=pick, binds_to=c.entity_id, label=word, origin="code"))
        attached += 1
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
    """References in the person's order, then the start frame, then the end frame: the fixed layout that makes
    `<IMAGE_REF_n>` equal the n-th image part of the request."""
    first, last = frame_of(bindings, "first_frame"), frame_of(bindings, "last_frame")
    return [*references_of(bindings), *([first] if first else []), *([last] if last else [])]


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


def build_omni_input(spec: RenderSpec) -> dict[str, Any]:
    """Spec → the Omni request, with every picture CITED. An attached picture the prompt never names drifts the
    frame, so the citation block is built from the same list as the payload. `<IMAGE_REF_n>` numbers the plain
    references 0..n-1 and those are the first n image parts; the frames come after and carry their own tags."""
    parts = [spec.prose.strip()]
    payload: list[dict[str, Any]] = []
    lines: list[str] = []
    for b in wire_order(spec.references):
        if b.slot == "first_frame":
            tag, line = FIRST_FRAME_TAG, f"{FIRST_FRAME_TAG} is the literal opening frame: {b.label}."
        elif b.slot == "last_frame":
            tag, line = LAST_FRAME_TAG, f"{LAST_FRAME_TAG} is the closing frame: {b.label}."
        else:
            tag = REF_TAG.format(n=sum(1 for p in payload if p["slot"] == "reference"))
            line = f"{tag} is {b.label}."
        payload.append(_part(b, tag))
        lines.append(line)
    if lines:
        parts.append("Reference images:\n" + "\n".join(lines))
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
    """The tags the built prompt cites, in the order they appear. Omni only (Veo cites by position)."""
    return re.findall(r"<(?:IMAGE_REF_\d+|FIRST_FRAME|LAST_FRAME)>", built["prompt"].split("Reference images:\n")[-1]
                      if "Reference images:\n" in built["prompt"] else "")


def tags_of(spec: RenderSpec) -> list[str]:
    """The name each picture goes by in the request, in wire order: `<IMAGE_REF_0>` for Omni, `image 1` for Veo, the
    frame tags for frames. What the panel shows beside each card, so a person sees the tags renumber on a reorder."""
    out: list[str] = []
    n = 0
    for b in wire_order(spec.references):
        if b.slot == "first_frame":
            out.append("start frame")
        elif b.slot == "last_frame":
            out.append("end frame")
        else:
            out.append(REF_TAG.format(n=n) if capability(spec.engine).api == "interactions" else f"image {n + 1}")
            n += 1
    return out


def describe_spec(spec: RenderSpec) -> str:
    """The settings in words, for a take's card: "Omni Flash · 720p · 16:9 · 8 s · 3 pictures · seed 1234"."""
    try:
        label = capability(spec.engine).label
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
    if first is not None and not cap.first_frame:
        out.append(_fail(f"{cap.label} cannot start from a picture."))
    if last is not None and not cap.last_frame:
        out.append(_fail(f"{cap.label} cannot aim at an end frame."))
    if plain and first is not None and not cap.refs_with_first_frame:
        out.append(_fail(f"{cap.label} takes either reference pictures or a start frame, not both."))
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
    out: list[Check] = []
    plain = references_of(spec.references)
    bound: dict[UUID, int] = {}
    for i, b in enumerate(plain):
        if b.binds_to is None:
            continue
        bound[b.binds_to] = bound.get(b.binds_to, 0) + 1
        name = facts.names.get(b.binds_to) or facts.seen.get(b.binds_to) or ""
        if name and not _named(spec.prose, name):
            out.append(_advisory(f"Image {i + 1} is {name}; the prompt never mentions them. "
                                 "The picture will drift the frame."))
        have, now = b.source.version, facts.current_versions.get(b.binds_to)
        if have is not None and now is not None and have < now:
            out.append(_advisory(f"The picture of {name or b.label} is from an older card (v{have}; now v{now})."))
    for who, n in bound.items():
        if n > 1:
            out.append(_advisory(f"{facts.names.get(who, 'Someone')} has {n} reference pictures."))
    for who, name in facts.seen.items():
        if who not in bound:
            out.append(_advisory(f"{name} is in the shot but has no reference picture."))
    for reason in facts.frame_stale:
        if frame_of(spec.references, "first_frame") is not None:
            out.append(_advisory(f"The start frame is out of date: {reason}."))
    return out
