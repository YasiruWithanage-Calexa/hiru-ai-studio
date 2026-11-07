"""What a scene costs to make (plan/2026-11-06d): the money rules, pure pydantic + stdlib.

Money is an integer number of MICRO-DOLLARS (1 USD = 1,000,000). No float is ever summed; the interface rounds to cents
for display. A cost is computed at READ time from metered usage and the dated price list (`Price.valid_from`): nothing
stores a money figure, so a price change applies to new work only and old spending keeps the price it was made at.

Rules that must not drift (each has a test):
  * EACH MARGIN IS APPLIED ONCE, only in `with_margin` / `with_retry`: video +10%, images +5%, text calls 0, and the
    +20% retry margin on the to-finish part only, after the kind margins (`scene_total`).
  * A MISSING PRICE IS A NOTE, NEVER ZERO AND NEVER A GUESS. The item is left out and `Costed.missing` says why.
  * NO BREAKDOWN LEAVES THE SERVER. `SceneTotal` keeps its parts for tests and logs; the API sends the total only.
  * Reasoning tokens are billed as output tokens. A `token_usage` row's `output_tokens` already includes them (the
    provider's completion count), so they are never added a second time.

Prices: `kind` "tokens" (per million tokens, matched by the longest `model_prefix`), "video_second" (matched by
`engine` + `model` + `resolution`) and "estimate" (a flat price of one frame or one prompt, matched by `model_prefix`
= "frame" | "prompt", used only when no history says what one costs).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.video_gen import ResolvedSettings, capability

MICROS_PER_USD = 1_000_000
CURRENCY = "USD"

WorkKind = Literal["text", "image", "video"]
PriceKind = Literal["tokens", "video_second", "estimate"]

# Basis points (1 bp = 0.01%) so no float enters the money. The person's decisions, 2026-11-06.
MARGIN: dict[str, int] = {"text": 0, "image": 500, "video": 1000}
RETRY_MARGIN = 2000

# The `token_usage.phase` values that are pictures. A closed list: a new image phase must be added here or it would be
# priced as text (`tests/contracts/test_costs.py` scans every manifest's phase for an image-like word).
IMAGE_PHASES: frozenset[str] = frozenset({"frame_render.image"})
# Rows that only meter a video render for the monthly usage %. The render itself is priced from `video_renders`.
METERED_PHASE_PREFIXES: tuple[str, ...] = ("video_render.",)

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(_Model):
    kind: PriceKind
    model_prefix: str = ""  # tokens: "gpt-5-mini"; estimate: "frame" | "prompt"
    engine: str = ""  # video_second
    model: str = ""  # video_second: "" matches any model of the engine
    resolution: str = ""  # video_second
    input_micros: int = Field(default=0, ge=0)  # tokens: per million tokens
    cached_input_micros: int = Field(default=0, ge=0)
    output_micros: int = Field(default=0, ge=0)
    per_second_micros: int = Field(default=0, ge=0)  # video_second
    unit_micros: int = Field(default=0, ge=0)  # estimate: one frame or one prompt, before margin
    valid_from: datetime = EPOCH
    note: str = ""


def usd(micros: int) -> float:
    """For logs and tests only: money is never summed as a float."""
    return micros / MICROS_PER_USD


def micros_of(dollars: str | int) -> int:
    """'1.25' -> 1_250_000, exactly (a decimal string, never a float)."""
    text = str(dollars)
    whole, _, frac = text.partition(".")
    frac = (frac + "000000")[:6]
    return int(whole or "0") * MICROS_PER_USD + int(frac or "0")


# ── margins ───────────────────────────────────────────────────────────────────────────────────────────────────


def _bp(micros: int, basis_points: int) -> int:
    """`micros` plus `basis_points`, rounded half up. Integer math only."""
    return (micros * (10_000 + basis_points) + 5_000) // 10_000


def with_margin(micros: int, kind: str) -> int:
    return _bp(micros, MARGIN[kind])


def with_retry(micros: int) -> int:
    return _bp(micros, RETRY_MARGIN)


# ── prices ────────────────────────────────────────────────────────────────────────────────────────────────────


def _utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def price_for(kind: PriceKind, keys: Mapping[str, str], at: datetime | str | None,
              prices: Iterable[Price]) -> Price | None:
    """The price valid at `at`, or None. Never a guess: no price means the caller reports it.

    tokens: `keys["model"]`, the longest `model_prefix` that is the name or a dated snapshot of it. video_second:
    `engine`, `resolution` and `model` ("" on a price matches any model; a named one beats it). estimate:
    `keys["name"]`. Among equals the latest `valid_from` that is not after `at` wins."""
    when = _utc(at)
    best: tuple[tuple[int, datetime], Price] | None = None
    for p in prices:
        if p.kind != kind or _utc(p.valid_from) > when:
            continue
        if kind == "tokens":
            name = keys.get("model", "").lower()
            prefix = p.model_prefix.lower()
            # A name or a dated snapshot of it ("gpt-5-2025-08-07"), never a different model that merely starts with it:
            # the lab found a bare prefix billed gpt-5.5 as gpt-5. An unlisted model has no price and is reported.
            if not prefix or not (name == prefix or name.startswith(prefix + "-")):
                continue
            rank = len(p.model_prefix)
        elif kind == "video_second":
            if p.engine != keys.get("engine") or p.resolution != keys.get("resolution"):
                continue
            if p.model and p.model != keys.get("model"):
                continue
            rank = 1 if p.model else 0
        else:
            if p.model_prefix != keys.get("name"):
                continue
            rank = 0
        order = (rank, _utc(p.valid_from))
        if best is None or order > best[0]:
            best = (order, p)
    return best[1] if best else None


# ── what a piece of work costs ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Costed:
    """An amount (margin included unless said otherwise) and, when its price was missing, the words for it."""

    micros: int = 0
    missing: tuple[str, ...] = ()


@dataclass
class Tally:
    """A running sum of `Costed`: micros and the (de-duplicated) missing-price notes."""

    micros: int = 0
    missing: list[str] = field(default_factory=list)

    def add(self, item: Costed) -> None:
        self.micros += item.micros
        for note in item.missing:
            if note not in self.missing:
                self.missing.append(note)

    def extend(self, items: Iterable[Costed]) -> Tally:
        for item in items:
            self.add(item)
        return self


def kind_of(phase: str) -> Literal["text", "image", "metered"]:
    """How a `token_usage` row is priced: a picture, a meter for a video (priced from its render instead), or text."""
    if phase in IMAGE_PHASES:
        return "image"
    if phase.startswith(METERED_PHASE_PREFIXES):
        return "metered"
    return "text"


def tokens_actual(row: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """One `token_usage` row at actual cost, no margin. Cached prompt tokens are billed at the cached rate."""
    model = str(row.get("model") or "")
    p = price_for("tokens", {"model": model}, row.get("created_at"), prices)
    if p is None:
        return Costed(0, (f"no price for {model or 'an unnamed model'}",))
    prompt, cached = int(row.get("input_tokens") or 0), int(row.get("cached_input_tokens") or 0)
    numerator = (max(prompt - cached, 0) * p.input_micros + cached * (p.cached_input_micros or p.input_micros)
                 + int(row.get("output_tokens") or 0) * p.output_micros)
    return Costed((numerator + MICROS_PER_USD // 2) // MICROS_PER_USD)


def cost_tokens(row: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """One `token_usage` row with its kind's margin. A video meter costs nothing here (see `cost_render`)."""
    kind = kind_of(str(row.get("phase") or ""))
    if kind == "metered":
        return Costed()
    actual = tokens_actual(row, prices)
    return Costed(with_margin(actual.micros, kind), actual.missing)


def _render_seconds(render: Mapping[str, Any]) -> int:
    usage = render.get("usage") or {}
    spec = render.get("spec") or {}
    return int(usage.get("seconds_rendered") or usage.get("provider_seconds") or spec.get("duration_s") or 0)


def render_billed(render: Mapping[str, Any]) -> bool:
    """A render that finished is billed. A failed or refused one only when the function recorded that the provider
    billed it (`usage.billed`; D-C, settled by the Phase 0 probe)."""
    if render.get("status") == "done":
        return True
    return bool((render.get("usage") or {}).get("billed"))


def video_actual(render: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """A render at actual cost: rendered seconds x takes made x the price per second. No margin."""
    if not render_billed(render):
        return Costed()
    spec = render.get("spec") or {}
    usage = render.get("usage") or {}
    keys = {"engine": str(render.get("engine") or spec.get("engine") or ""),
            "model": str(render.get("model") or spec.get("model") or ""),
            "resolution": str(spec.get("resolution") or usage.get("resolution") or "")}
    p = price_for("video_second", keys, render.get("created_at"), prices)
    if p is None:
        return Costed(0, (f"no price for {keys['engine'] or 'video'} at {keys['resolution'] or 'this size'}",))
    takes = int(usage.get("takes_made") or 1)
    return Costed(_render_seconds(render) * takes * p.per_second_micros)


def cost_render(render: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    actual = video_actual(render, prices)
    return Costed(with_margin(actual.micros, "video"), actual.missing)


def estimate_shot_video(resolved: ResolvedSettings, prices: Sequence[Price], at: datetime | str | None = None
                        ) -> Costed:
    """What the shot's next video will cost: duration x takes x price per second, then the video margin. It takes the
    output of `video_gen.resolve`, so the estimate uses the settings the render would use."""
    model = resolved.model or capability(resolved.engine).model
    p = price_for("video_second", {"engine": resolved.engine, "model": model, "resolution": resolved.resolution},
                  at, prices)
    if p is None:
        return Costed(0, (f"no price for {resolved.engine} at {resolved.resolution}",))
    return Costed(with_margin(resolved.duration_s * resolved.takes * p.per_second_micros, "video"))


def estimate_unit(name: Literal["frame", "prompt"], prices: Sequence[Price], at: datetime | str | None = None
                  ) -> Costed:
    """The seeded flat price of one frame or one prompt (the last resort when no history exists), with its margin."""
    p = price_for("estimate", {"name": name}, at, prices)
    if p is None:
        return Costed(0, (f"no estimate price for a {name}",))
    return Costed(with_margin(p.unit_micros, "image" if name == "frame" else "text"))


def median(values: Sequence[int]) -> int | None:
    """The median of whole micro-dollars (the lower middle of an even count, so it stays an integer)."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


# ── a scene's total ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SceneTotal:
    """The parts are for tests and debug logs. Only `total_micros`, `designed` and `complete` go on the wire."""

    spent_micros: int
    to_finish_micros: int  # before the retry margin
    total_micros: int
    complete: bool
    missing: tuple[str, ...] = ()
    parts: Mapping[str, int] = field(default_factory=dict)


def scene_total(spent: Iterable[Costed], to_finish: Iterable[Costed],
                parts: Mapping[str, int] | None = None) -> SceneTotal:
    """Each part is summed with its own margins already inside it; the retry margin is then applied ONCE, to the
    to-finish sum only: work already done cannot be retried (D-B)."""
    a = Tally().extend(spent)
    b = Tally().extend(to_finish)
    notes = list(a.missing) + [n for n in b.missing if n not in a.missing]
    return SceneTotal(spent_micros=a.micros, to_finish_micros=b.micros, total_micros=a.micros + with_retry(b.micros),
                      complete=not notes, missing=tuple(notes), parts=dict(parts or {}))


def actual_total(rows: Iterable[Mapping[str, Any]], prices: Sequence[Price]) -> Costed:
    """Rows at actual cost without margins: what the live scripts print."""
    t = Tally()
    for r in rows:
        t.add(tokens_actual(r, prices))
    return Costed(t.micros, tuple(t.missing))


# ── the seeded list prices ────────────────────────────────────────────────────────────────────────────────────

_NOTE = "list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)"


def _tok(prefix: str, inp: str, cached: str, out: str, note: str = _NOTE) -> Price:
    return Price(kind="tokens", model_prefix=prefix, input_micros=micros_of(inp), cached_input_micros=micros_of(cached),
                 output_micros=micros_of(out), note=note)


def _vid(engine: str, resolution: str, per_second: str, note: str = _NOTE) -> Price:
    return Price(kind="video_second", engine=engine, resolution=resolution, per_second_micros=micros_of(per_second),
                 note=note)


# What `Database/upgrade_v16_to_v17.sql` seeds. A model or size that is not listed has NO price on purpose: the cost
# says "some prices are missing" until an admin adds one. gpt-5 and its smaller sizes are the prices
# the live cost scripts used (OpenAI standard tier, USD per million tokens).
SEED_PRICES: tuple[Price, ...] = (
    _tok("gpt-5-nano", "0.05", "0.005", "0.40", "OpenAI list price, standard tier"),
    _tok("gpt-5-mini", "0.25", "0.025", "2.00", "OpenAI list price, standard tier"),
    _tok("gpt-5", "1.25", "0.125", "10.00", "OpenAI list price, standard tier"),
    _tok("gpt-5.5", "5.00", "0.50", "30.00", "OpenAI list price, read 2026-11-06 by lab/cinematic: confirm"),
    _tok("gpt-6.1-sol", "2.00", "0.10", "10.00",
         "OpenAI list price below 272K input (2x input above it), read 2026-11-06 by lab/cinematic: confirm"),
    _tok("text-embedding-3-large", "0.13", "0.13", "0"),
    _tok("text-embedding-3-small", "0.02", "0.02", "0"),
    _tok("gpt-image-2", "8.00", "2.00", "30.00"),
    _vid("veo_3_1", "720p", "0.40"),
    _vid("veo_3_1", "1080p", "0.40"),
    _vid("veo_3_1_fast", "720p", "0.10"),
    _vid("veo_3_1_fast", "1080p", "0.12"),
    _vid("omni_flash", "720p", "0.10", "derived from the preview's token rate: confirm (plan/2026-11-06d Phase 0)"),
    Price(kind="estimate", model_prefix="frame", unit_micros=micros_of("0.08"),
          note="one first frame at medium quality: used only when no frame has been made yet"),
    Price(kind="estimate", model_prefix="prompt", unit_micros=micros_of("0.02"),
          note="one video prompt: used only when none has been made yet"),
)
