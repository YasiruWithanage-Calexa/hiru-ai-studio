"""What work costs (plan/2026-11-06d, plan/2026-11-23): the money rules, pure pydantic + stdlib.

Money is an integer number of MICRO-DOLLARS (1 USD = 1,000,000). No float is ever summed; the interface rounds to cents
for display. A cost is computed at READ time from metered usage and the dated price list (`Price.valid_from`): nothing
stores a money figure, so a price change applies to new work only and old spending keeps the price it was made at.

Two figures exist for every piece of work:
  * PROVIDER COST (`tokens_actual`, `video_actual`): what the provider charges us. Never leaves the server.
  * FINAL PRICE (`cost_tokens`, `cost_render`, the estimates): provider cost + the studio's margin for its bucket, from
    `src/api/margins.yaml` (dated like prices). This is the only figure any person sees. The API reads the file and
    hands its content to `parse_margins`, so this package stays free of YAML (every function bundles it).

Rules that must not drift (each has a test):
  * THE MARGINS ARE SECRET. They live in `src/api/margins.yaml` and in memory here. No response, page or log line
    above DEBUG carries a margin or a provider cost.
  * EACH MARGIN IS APPLIED ONCE, only in `with_margin`: the bucket margin on every item. There is no retry margin
    (the person, plan/2026-11-23b): a scene's figure is spent + what is left to make.
  * A MISSING PRICE IS A NOTE, NEVER ZERO AND NEVER A GUESS. The item is left out and `Costed.missing` says why.
  * A MISSING OR BROKEN MARGINS FILE IS AN ERROR, never a 0 % margin.
  * NO BREAKDOWN LEAVES THE SERVER. `SceneTotal` keeps its parts for tests and logs; the API sends the total only.
  * Reasoning tokens are billed as output tokens. A `token_usage` row's `output_tokens` already includes them (the
    provider's completion count), so they are never added a second time.

Prices: `kind` "tokens" (per million tokens, matched by `model_prefix`: the name or a dated snapshot of it),
"video_tokens" (a video model billed per million tokens, e.g. Gemini Omni: input, video output, text/thinking output),
"video_second" (matched by `engine` + `model` + `resolution`: the fallback for a render without token counts, and what
an estimate uses) and "estimate" (a flat price of one frame or one prompt, matched by `model_prefix` = "frame" |
"prompt", used only when no history says what one costs). A tokens price may also carry an image-input rate (pictures
sent to an image model) and long-context rates (a call above `long_context_from` input tokens).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.video_gen import ResolvedSettings, capability

MICROS_PER_USD = 1_000_000
CURRENCY = "USD"

WorkKind = Literal["text", "image", "video"]
Bucket = Literal["llm", "image", "video"]
PriceKind = Literal["tokens", "video_tokens", "video_second", "estimate"]

BUCKETS: tuple[Bucket, ...] = ("llm", "image", "video")
# `kind_of` says text / image; the margins file and the Usage page say llm / image / video.
BUCKET_OF_KIND: dict[str, Bucket] = {"text": "llm", "llm": "llm", "image": "image", "video": "video"}

# The `token_usage.phase` values that are pictures. A closed list: a new image phase must be added here or it would be
# priced as text (`tests/contracts/test_costs.py` scans every manifest's phase for an image-like word).
IMAGE_PHASES: frozenset[str] = frozenset({"frame_render.image"})
# Rows that only meter a video render for the monthly usage %. The render itself is priced from `video_renders`.
METERED_PHASE_PREFIXES: tuple[str, ...] = ("video_render.",)

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
MAX_MARGIN_BP = 50_000  # 500 %


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Price(_Model):
    kind: PriceKind
    model_prefix: str = ""  # tokens / video_tokens: "gpt-5-mini"; estimate: "frame" | "prompt"
    engine: str = ""  # video_second
    model: str = ""  # video_second: "" matches any model of the engine
    resolution: str = ""  # video_second
    input_micros: int = Field(default=0, ge=0)  # tokens / video_tokens: per million tokens (text input)
    cached_input_micros: int = Field(default=0, ge=0)
    output_micros: int = Field(default=0, ge=0)  # video_tokens: the VIDEO output rate
    # tokens: pictures sent to an image model (gpt-image-2). 0 = pictures cost what text input costs.
    image_input_micros: int = Field(default=0, ge=0)
    cached_image_input_micros: int = Field(default=0, ge=0)
    # video_tokens: text and thinking output. 0 = billed at `output_micros`.
    text_output_micros: int = Field(default=0, ge=0)
    # tokens: a call with MORE input tokens than this is billed at the long rates (0 = no long-context tier). A long
    # rate of 0 keeps the short one.
    long_context_from: int = Field(default=0, ge=0)
    long_input_micros: int = Field(default=0, ge=0)
    long_cached_input_micros: int = Field(default=0, ge=0)
    long_output_micros: int = Field(default=0, ge=0)
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


def _utc(value: datetime | date | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):  # a date: UTC midnight
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ── margins (src/api/margins.yaml) ─────────────────────────────────────────────────────────────────────────


class MarginsError(RuntimeError):
    """The margins file is missing or wrong. The API does not start: a silent 0 % would under-bill everything."""


@dataclass(frozen=True)
class MarginEntry:
    start: datetime
    bp: Mapping[str, int]  # bucket -> basis points (1 bp = 0.01 %)


@dataclass(frozen=True)
class Margins:
    entries: tuple[MarginEntry, ...]  # oldest first

    def at(self, bucket: str, when: datetime | str | None = None) -> int:
        """The basis points of `bucket` in force at `when` (now when None). Before the first entry: the first entry,
        so work older than the file still gets a margin (never 0 by accident)."""
        name = BUCKET_OF_KIND[bucket]
        moment = _utc(when)
        chosen = self.entries[0]
        for entry in self.entries:
            if entry.start <= moment:
                chosen = entry
        return chosen.bp[name]

    def starts(self) -> list[datetime]:
        return [e.start for e in self.entries]


_PERCENT = re.compile(r"^\d{1,3}(\.\d{1,2})?$")


def _bp_of(value: Any, where: str) -> int:
    """A percent as written in the file ('12.5', 20) -> basis points, from its text: never through float arithmetic."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise MarginsError(f"{where}: {value!r} is not a percent")
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if not _PERCENT.match(text):
        raise MarginsError(f"{where}: {value!r} must be a percent from 0 to 500 with at most two decimals")
    whole, _, frac = text.partition(".")
    bp = int(whole) * 100 + int((frac + "00")[:2])
    if bp > MAX_MARGIN_BP:
        raise MarginsError(f"{where}: {value!r} is above 500 %")
    return bp


def parse_margins(raw: Any, source: str = "margins.yaml") -> Margins:
    """Check the margins file's content (read by the API, `api.margins`) and turn percents into basis points. Raises
    `MarginsError` naming the source and the fault."""
    if not isinstance(raw, dict) or not isinstance(raw.get("margins"), list) or not raw["margins"]:
        raise MarginsError(f"{source}: needs a non-empty `margins:` list")
    entries: list[MarginEntry] = []
    for n, item in enumerate(raw["margins"], start=1):
        where = f"{source} margins entry {n}"
        if not isinstance(item, dict):
            raise MarginsError(f"{where}: must be a mapping")
        unknown = set(item) - {"from", *BUCKETS}
        if unknown:
            raise MarginsError(f"{where}: unknown keys {sorted(unknown)}")
        start = item.get("from")
        if isinstance(start, str):
            try:
                start = date.fromisoformat(start)
            except ValueError as exc:
                raise MarginsError(f"{where}: `from` must be a date like 2026-01-01") from exc
        if not isinstance(start, date):
            raise MarginsError(f"{where}: `from` must be a date like 2026-01-01")
        missing = [b for b in BUCKETS if b not in item]
        if missing:
            raise MarginsError(f"{where}: missing {', '.join(missing)}")
        entry = MarginEntry(_utc(start), {b: _bp_of(item[b], f"{where} {b}") for b in BUCKETS})
        if entries and entry.start <= entries[-1].start:
            raise MarginsError(f"{where}: `from` must be later than the entry before it")
        entries.append(entry)
    if "estimate" in raw:  # plan/2026-11-23b: an old copy of the file must not slip through with a retry margin
        raise MarginsError(f"{source}: `estimate:` is no longer used (there is no retry margin); remove it")
    unknown_keys = set(raw) - {"margins"}
    if unknown_keys:
        raise MarginsError(f"{source}: unknown keys {sorted(unknown_keys)}")
    return Margins(tuple(entries))


_margins: Margins | None = None


def margins() -> Margins:
    """The margins this process prices with. The API installs them at start-up (`api.margins.install`); pricing
    before that is an error, never a 0 % margin."""
    if _margins is None:
        raise MarginsError("the margins are not loaded: the API reads src/api/margins.yaml at start-up "
                           "(api.margins.install)")
    return _margins


def use_margins(value: Margins | None) -> None:
    """Install the margins this process prices with (the API at start-up, and tests). None = none installed."""
    global _margins
    _margins = value


# ── margins applied ───────────────────────────────────────────────────────────────────────────────────────────


def _bp(micros: int, basis_points: int) -> int:
    """`micros` plus `basis_points`, rounded half up. Integer math only."""
    return (micros * (10_000 + basis_points) + 5_000) // 10_000


def with_margin(micros: int, kind: str, at: datetime | str | None = None) -> int:
    """Provider cost -> final price: the margin of `kind` ("text"/"llm", "image", "video") in force at `at`."""
    return _bp(micros, margins().at(kind, at))


# ── prices ────────────────────────────────────────────────────────────────────────────────────────────────────


def _names_model(prefix: str, name: str) -> bool:
    """A name or a dated snapshot of it ("gpt-5-2025-08-07"), never a different model that merely starts with it:
    the lab found a bare prefix billed gpt-5.5 as gpt-5."""
    prefix, name = prefix.lower(), name.lower()
    return bool(prefix) and (name == prefix or name.startswith(prefix + "-"))


def price_for(kind: PriceKind, keys: Mapping[str, str], at: datetime | str | None,
              prices: Iterable[Price]) -> Price | None:
    """The price valid at `at`, or None. Never a guess: no price means the caller reports it.

    tokens / video_tokens: `keys["model"]`, the longest `model_prefix` that is the name or a dated snapshot of it.
    video_second: `engine`, `resolution` and `model` ("" on a price matches any model; a named one beats it).
    estimate: `keys["name"]`. Among equals the latest `valid_from` that is not after `at` wins."""
    when = _utc(at)
    best: tuple[tuple[int, datetime], Price] | None = None
    for p in prices:
        if p.kind != kind or _utc(p.valid_from) > when:
            continue
        if kind in ("tokens", "video_tokens"):
            if not _names_model(p.model_prefix, keys.get("model", "")):
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


def price_starts(prices: Iterable[Price]) -> list[datetime]:
    """Every moment a token price changes, sorted: inside two of these no token price changes."""
    return sorted({_utc(p.valid_from) for p in prices if p.kind == "tokens"})


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


def _round(numerator: int) -> int:
    """Token counts x per-million rates -> micro-dollars, rounded half up."""
    return (numerator + MICROS_PER_USD // 2) // MICROS_PER_USD


def is_long(row: Mapping[str, Any], p: Price) -> bool:
    """Billed at the long-context rates. A summed group (`usage_totals`) says so itself (`long`): its summed input
    says nothing about each call's size."""
    if "long" in row:
        return bool(row["long"]) and p.long_context_from > 0
    return p.long_context_from > 0 and int(row.get("input_tokens") or 0) > p.long_context_from


def picture_split(row: Mapping[str, Any]) -> tuple[int, int]:
    """(picture input tokens, cached picture tokens) of one row: a row that does not say (None) is all pictures;
    cached tokens come off the text first. A summed group carries both already summed row by row
    (`cached_image_input_tokens`), because the split of a sum is not the sum of the splits."""
    prompt = int(row.get("input_tokens") or 0)
    cached = min(int(row.get("cached_input_tokens") or 0), prompt)
    raw = row.get("image_input_tokens")
    pictures = prompt if raw is None else min(int(raw), prompt)
    if "cached_image_input_tokens" in row:
        return pictures, min(int(row["cached_image_input_tokens"] or 0), pictures, cached)
    return pictures, min(max(cached - (prompt - pictures), 0), pictures)


def tokens_actual(row: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """One `token_usage` row (or a group of rows summed, see `usage_totals`) at PROVIDER cost, no margin.

    Cached input is billed at the cached rate. A call above the price's long-context threshold is billed at the long
    rates. With an image-input rate, the row's `image_input_tokens` are billed at it and the rest of the input as text;
    a row that does not say (`None`: written before schema v29) is billed as all pictures, as it was before the split.
    Cached tokens come off the text part first, then the pictures."""
    model = str(row.get("model") or "")
    p = price_for("tokens", {"model": model}, row.get("created_at"), prices)
    if p is None:
        return Costed(0, (f"no price for {model or 'an unnamed model'}",))
    prompt = int(row.get("input_tokens") or 0)
    cached = int(row.get("cached_input_tokens") or 0)
    output = int(row.get("output_tokens") or 0)
    long = is_long(row, p)
    rate_in = (p.long_input_micros if long and p.long_input_micros else p.input_micros)
    rate_cached = (p.long_cached_input_micros if long and p.long_cached_input_micros
                   else p.cached_input_micros or rate_in)
    rate_out = (p.long_output_micros if long and p.long_output_micros else p.output_micros)
    if p.image_input_micros:
        pictures, cached_pictures = picture_split(row)
        text = prompt - pictures
        cached_text = min(cached, prompt) - cached_pictures
        numerator = ((text - cached_text) * rate_in + cached_text * rate_cached
                     + (pictures - cached_pictures) * p.image_input_micros
                     + cached_pictures * (p.cached_image_input_micros or p.image_input_micros)
                     + output * rate_out)
    else:
        numerator = max(prompt - cached, 0) * rate_in + min(cached, prompt) * rate_cached + output * rate_out
    return Costed(_round(numerator))


def cost_tokens(row: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """One `token_usage` row at its FINAL price (its kind's margin in force when it was made). A video meter costs
    nothing here (see `cost_render`)."""
    kind = kind_of(str(row.get("phase") or ""))
    if kind == "metered":
        return Costed()
    actual = tokens_actual(row, prices)
    return Costed(with_margin(actual.micros, kind, row.get("created_at")), actual.missing)


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


def render_model(render: Mapping[str, Any]) -> str:
    spec = render.get("spec") or {}
    return str(render.get("model") or spec.get("model") or "")


def _render_tokens(render: Mapping[str, Any], prices: Sequence[Price]) -> Costed | None:
    """A render priced by the tokens the provider reported (Gemini Omni): input x input rate + video tokens x video
    rate + thinking tokens x text rate. None when the render has no token counts or its model no token price: the
    caller then prices it by the second."""
    usage = render.get("usage") or {}
    completion = int(usage.get("completion_tokens") or 0)
    if not completion:
        return None
    p = price_for("video_tokens", {"model": render_model(render)}, render.get("created_at"), prices)
    if p is None:
        return None
    if "video_tokens" in usage:
        video = int(usage.get("video_tokens") or 0)
        thought = int(usage.get("thought_tokens") or 0)
    else:  # written before the split: all of it at the video rate (what it nearly all is)
        video, thought = completion, 0
    numerator = (int(usage.get("prompt_tokens") or 0) * p.input_micros + video * p.output_micros
                 + thought * (p.text_output_micros or p.output_micros))
    return Costed(_round(numerator))


def video_actual(render: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """A render at PROVIDER cost, no margin: by its tokens when the provider reported them and a token price exists,
    else rendered seconds x takes made x the price per second."""
    if not render_billed(render):
        return Costed()
    by_tokens = _render_tokens(render, prices)
    if by_tokens is not None:
        return by_tokens
    spec = render.get("spec") or {}
    usage = render.get("usage") or {}
    keys = {"engine": str(render.get("engine") or spec.get("engine") or ""),
            "model": render_model(render),
            "resolution": str(spec.get("resolution") or usage.get("resolution") or "")}
    p = price_for("video_second", keys, render.get("created_at"), prices)
    if p is None:
        return Costed(0, (f"no price for {keys['engine'] or 'video'} at {keys['resolution'] or 'this size'}",))
    takes = int(usage.get("takes_made") or 1)
    return Costed(_render_seconds(render) * takes * p.per_second_micros)


def cost_render(render: Mapping[str, Any], prices: Sequence[Price]) -> Costed:
    """A render at its FINAL price."""
    actual = video_actual(render, prices)
    return Costed(with_margin(actual.micros, "video", render.get("created_at")), actual.missing)


def estimate_shot_video(resolved: ResolvedSettings, prices: Sequence[Price], at: datetime | str | None = None
                        ) -> Costed:
    """What the shot's next video will cost, FINAL: duration x takes x price per second, then the video margin. It
    takes the output of `video_gen.resolve`, so the estimate uses the settings the render would use."""
    model = resolved.model or capability(resolved.engine).model
    p = price_for("video_second", {"engine": resolved.engine, "model": model, "resolution": resolved.resolution},
                  at, prices)
    if p is None:
        return Costed(0, (f"no price for {resolved.engine} at {resolved.resolution}",))
    return Costed(with_margin(resolved.duration_s * resolved.takes * p.per_second_micros, "video", at))


def estimate_unit(name: Literal["frame", "prompt"], prices: Sequence[Price], at: datetime | str | None = None
                  ) -> Costed:
    """The seeded flat price of one frame or one prompt (the last resort when no history exists), FINAL."""
    p = price_for("estimate", {"name": name}, at, prices)
    if p is None:
        return Costed(0, (f"no estimate price for a {name}",))
    return Costed(with_margin(p.unit_micros, "image" if name == "frame" else "text", at))


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
    to_finish_micros: int
    total_micros: int
    complete: bool
    missing: tuple[str, ...] = ()
    parts: Mapping[str, int] = field(default_factory=dict)


def scene_total(spent: Iterable[Costed], to_finish: Iterable[Costed],
                parts: Mapping[str, int] | None = None) -> SceneTotal:
    """Spent + what is left to make, each item with its own margin already inside it. No retry margin
    (plan/2026-11-23b)."""
    a = Tally().extend(spent)
    b = Tally().extend(to_finish)
    notes = list(a.missing) + [n for n in b.missing if n not in a.missing]
    return SceneTotal(spent_micros=a.micros, to_finish_micros=b.micros, total_micros=a.micros + b.micros,
                      complete=not notes, missing=tuple(notes), parts=dict(parts or {}))


def actual_total(rows: Iterable[Mapping[str, Any]], prices: Sequence[Price]) -> Costed:
    """Rows at provider cost without margins: what the live scripts print."""
    t = Tally()
    for r in rows:
        t.add(tokens_actual(r, prices))
    return Costed(t.micros, tuple(t.missing))


# ── the seeded list prices ────────────────────────────────────────────────────────────────────────────────────

_OPENAI = "OpenAI list price, standard tier (developers.openai.com/api/docs/pricing, read 2026-11-23)"
_GOOGLE = "Google list price, standard paid tier (aistudio.google.com/docs/pricing, read 2026-11-23)"
_OLD = "list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)"
_RETIRED = "retired engine (plan/2026-11-19): kept so renders made with it keep their price"
LONG_CONTEXT = 272_000  # OpenAI bills a call above this many input tokens at the long-context rates


def _tok(prefix: str, inp: str, cached: str, out: str, note: str = _OPENAI, *, image: str = "",
         cached_image: str = "", long: tuple[str, str, str] | None = None) -> Price:
    extra: dict[str, Any] = {}
    if image:
        extra |= {"image_input_micros": micros_of(image), "cached_image_input_micros": micros_of(cached_image or image)}
    if long:
        extra |= {"long_context_from": LONG_CONTEXT, "long_input_micros": micros_of(long[0]),
                  "long_cached_input_micros": micros_of(long[1]), "long_output_micros": micros_of(long[2])}
    return Price(kind="tokens", model_prefix=prefix, input_micros=micros_of(inp), cached_input_micros=micros_of(cached),
                 output_micros=micros_of(out), note=note, **extra)


def _vid(engine: str, resolution: str, per_second: str, note: str = _OLD, model: str = "") -> Price:
    return Price(kind="video_second", engine=engine, model=model, resolution=resolution,
                 per_second_micros=micros_of(per_second), note=note)


OMNI_12 = "gemini-omni-1.2-flash"

# What the database holds after `Database/upgrade_v28_to_v29.sql` (the v17 rows, corrected and completed). A model or
# size that is not listed has NO price on purpose: a cost says "some prices are missing" until an admin adds one.
SEED_PRICES: tuple[Price, ...] = (
    _tok("gpt-5-nano", "0.05", "0.005", "0.40"),
    _tok("gpt-5-mini", "0.25", "0.025", "2.00"),
    _tok("gpt-5", "1.25", "0.125", "10.00"),
    _tok("gpt-5.5", "5.00", "0.50", "30.00", long=("10.00", "1.00", "45.00")),
    _tok("gpt-6.1-sol", "2.00", "0.10", "10.00", long=("4.00", "0.20", "15.00")),
    _tok("gpt-6.1-terra", "1.00", "0.05", "5.00", long=("2.00", "0.10", "7.50")),
    _tok("text-embedding-3-large", "0.13", "0.13", "0"),
    _tok("text-embedding-3-small", "0.02", "0.02", "0"),
    # Text input 5.00 / cached 1.25; pictures sent in 8.00 / cached 2.00; the picture made 30.00.
    _tok("gpt-image-2", "5.00", "1.25", "30.00", image="8.00", cached_image="2.00"),
    # Gemini Omni 1.2 Flash is billed per token: input 1.50 (text and pictures), the video 12.00, text and thinking
    # 9.00. The per-second rows below are Google's own effective figures for the same rate (1,931 / 5,792 / 8,688
    # tokens a second): the fallback for a render without token counts, and what a scene estimate uses.
    Price(kind="video_tokens", model_prefix=OMNI_12, input_micros=micros_of("1.50"), output_micros=micros_of("12.00"),
          text_output_micros=micros_of("9.00"), note=_GOOGLE),
    _vid("omni_flash", "360p", "0.023", _GOOGLE),
    _vid("omni_flash", "720p", "0.07", _GOOGLE),
    _vid("omni_flash", "1080p", "0.104", _GOOGLE),
    _vid("omni_flash", "720p", "0.10", _RETIRED, model="gemini-omni-1.1-flash"),
    _vid("veo_3_1", "720p", "0.40", _RETIRED),
    _vid("veo_3_1", "1080p", "0.40", _RETIRED),
    _vid("veo_3_1_fast", "720p", "0.10", _RETIRED),
    _vid("veo_3_1_fast", "1080p", "0.12", _RETIRED),
    Price(kind="estimate", model_prefix="frame", unit_micros=micros_of("0.08"),
          note="one first frame at medium quality: used only when no frame has been made yet"),
    Price(kind="estimate", model_prefix="prompt", unit_micros=micros_of("0.02"),
          note="one shot's prompts (first frame + video) by the Shot prompt agent (lab/shot_prompts: $0.007-0.023 a "
               "shot, plan/2026-11-20d D12): used only when none has been made yet"),
)

# List prices code knows that the database does NOT seed (no migration adds them): they price what code itself caps
# before a call, never a bill. plan/2026-11-20c D18: the Camera agent (gpt-6.1-sol, medium), as lab/camera_agent
# measured it. Its real spend is metered like every call (`token_usage`, priced by the gpt-6.1-sol row).
UNSEEDED_PRICES: tuple[Price, ...] = (
    Price(kind="estimate", model_prefix="camera", unit_micros=micros_of("0.10"),
          note="the Camera agent designing one scene (lab: $0.087-0.099 for 18-22 clips)"),
    Price(kind="estimate", model_prefix="camera_ask", unit_micros=micros_of("0.04"),
          note="one \"Ask Camera\" redo of a shot (lab: $0.038)"),
)
# Every list price code knows: what a turn budget prices its calls with (plan/2026-11-13 §3.8).
LIST_PRICES: tuple[Price, ...] = SEED_PRICES + UNSEEDED_PRICES
