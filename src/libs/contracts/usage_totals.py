"""A month's spending in USD for Settings → Usage (plan/2026-11-23): the total and each production, in three buckets.

    Chat & decisions (llm)   `token_usage` rows priced as text (`costs.kind_of`)
    Image generation (image) `token_usage` rows priced as pictures
    Video generation (video) `video_renders` the provider billed (`costs.render_billed`)

Every figure is a FINAL price (`contracts.costs`: provider cost + the bucket's margin in force when the work was made).
Provider cost and margins never leave this module's callers: `MonthUsage` holds final micro-dollars only.

A month holds tens of thousands of `token_usage` rows, so they are SUMMED first (by the database's
`token_usage_totals`, or `group_rows` here when the database is older), per production, model, kind, price interval
and long/short call. `boundaries` are every moment a token price or a margin changes, so inside one interval each
group has one price and one margin, and pricing the sum is pricing each row (to within the rounding of one
micro-dollar per row, which the page's cents hide). Video renders are few and priced one by one.
"""
from __future__ import annotations

import bisect
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from contracts import cost_parts, costs
from contracts.cost_parts import Part, PurposeTotals
from contracts.costs import Bucket, Margins, Price

FIRST_MONTH = "2026-01"  # nothing was metered before the studio's first month


@dataclass
class BucketTotals:
    """Final micro-dollars per bucket."""

    llm: int = 0
    image: int = 0
    video: int = 0

    def add(self, bucket: Bucket, micros: int) -> None:
        setattr(self, bucket, getattr(self, bucket) + micros)

    @property
    def total(self) -> int:
        return self.llm + self.image + self.video


@dataclass
class MonthUsage:
    total: BucketTotals = field(default_factory=BucketTotals)
    # production id ("" = calls tied to no production) -> its totals
    productions: dict[str, BucketTotals] = field(default_factory=dict)
    # (what has no price, its bucket) -> how many calls or renders were left out
    missing: dict[tuple[str, Bucket], int] = field(default_factory=dict)
    # plan/2026-11-23b: the same money split by purpose (production setup, episode setup, scene)
    purpose: PurposeTotals = field(default_factory=PurposeTotals)
    purposes: dict[str, PurposeTotals] = field(default_factory=dict)

    def add(self, production_id: str, bucket: Bucket, micros: int, part: Part = "scene") -> None:
        self.total.add(bucket, micros)
        self.productions.setdefault(production_id, BucketTotals()).add(bucket, micros)
        self.purpose.add(part, micros)
        self.purposes.setdefault(production_id, PurposeTotals()).add(part, micros)

    def note_missing(self, what: str, bucket: Bucket, count: int) -> None:
        key = (what, bucket)
        self.missing[key] = self.missing.get(key, 0) + count


# ── the month ─────────────────────────────────────────────────────────────────────────────────────────────────


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def month_bounds(month: str | None, now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """("2026-11", the 1st 00:00 UTC, the next 1st 00:00 UTC). None = the current month. A month before
    `FIRST_MONTH` or after the current one is a `ValueError` (the router answers 422)."""
    now = now or datetime.now(UTC)
    current = f"{now.year:04d}-{now.month:02d}"
    label = month or current
    try:
        year_text, month_text = label.split("-")
        if len(year_text) != 4 or len(month_text) != 2:
            raise ValueError
        year, mon = int(year_text), int(month_text)
        since = _month_start(year, mon)
    except ValueError as exc:
        raise ValueError(f"{label!r} is not a month like 2026-11") from exc
    if label < FIRST_MONTH or label > current:
        raise ValueError(f"{label} is outside {FIRST_MONTH} to {current}")
    until = _month_start(year + 1, 1) if mon == 12 else _month_start(year, mon + 1)
    return label, since, until


def boundaries(prices: Iterable[Price], margins: Margins) -> list[datetime]:
    """Every moment a token price or a margin changes, sorted. Inside two of them neither changes."""
    return sorted(set(costs.price_starts(prices)) | set(margins.starts()))


def single_long_from(prices: Iterable[Price]) -> int | None:
    """The one long-context threshold every priced model shares (0 = none has one), or None when they differ: the
    database function then cannot sort long calls from short ones and the API groups the rows itself."""
    found = {p.long_context_from for p in prices if p.kind == "tokens" and p.long_context_from}
    if len(found) > 1:
        return None
    return found.pop() if found else 0


def slot_of(at: datetime | str, bounds: Sequence[datetime]) -> int:
    """Like Postgres `width_bucket(at, bounds)`: 0 before the first boundary, n from bounds[n-1]."""
    moment = at if isinstance(at, datetime) else datetime.fromisoformat(at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return bisect.bisect_right(list(bounds), moment)


def slot_start(slot: int, bounds: Sequence[datetime], since: datetime) -> datetime:
    """A moment inside the slot (and the month): any one prices the same."""
    if slot <= 0:
        return since
    return max(since, bounds[slot - 1])


# ── summing rows (the database function's twin) ───────────────────────────────────────────────────────────────


def group_rows(rows: Iterable[Mapping[str, Any]], bounds: Sequence[datetime],
               is_long: Callable[[Mapping[str, Any]], bool]) -> list[dict[str, Any]]:
    """`token_usage` rows summed as `public.token_usage_totals` sums them: per production, model, kind, slot,
    long/short, phase and job (the last two decide the purpose, plan/2026-11-23b); video meter rows left out. Every
    part that is not linear is split row by row before it is summed
    (`costs.picture_split`: pictures, cached pictures; cached input capped at the input), so the sums price exactly
    as the rows do."""
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        kind = costs.kind_of(str(r.get("phase") or ""))
        if kind == "metered":
            continue
        key = (str(r.get("production_id") or ""), str(r.get("model") or ""), kind,
               slot_of(r["created_at"], bounds), bool(is_long(r)), str(r.get("phase") or ""),
               str(r.get("job_id") or ""))
        g = out.setdefault(key, {"production_id": key[0] or None, "model": key[1], "kind": kind, "slot": key[3],
                                 "long": key[4], "phase": key[5], "job_id": key[6] or None, "calls": 0,
                                 "input_tokens": 0, "image_input_tokens": 0,
                                 "cached_input_tokens": 0, "cached_image_input_tokens": 0, "output_tokens": 0})
        prompt = int(r.get("input_tokens") or 0)
        pictures, cached_pictures = costs.picture_split(r)
        g["calls"] += 1
        g["input_tokens"] += prompt
        g["image_input_tokens"] += pictures
        g["cached_input_tokens"] += min(int(r.get("cached_input_tokens") or 0), prompt)
        g["cached_image_input_tokens"] += cached_pictures
        g["output_tokens"] += int(r.get("output_tokens") or 0)
    return list(out.values())


def long_by_price(prices: Sequence[Price]) -> Callable[[Mapping[str, Any]], bool]:
    """Long/short for one row by its own model's price (the fallback when thresholds differ)."""
    def check(row: Mapping[str, Any]) -> bool:
        p = costs.price_for("tokens", {"model": str(row.get("model") or "")}, row.get("created_at"), prices)
        return p is not None and costs.is_long({"input_tokens": row.get("input_tokens")}, p)
    return check


def long_by_threshold(threshold: int) -> Callable[[Mapping[str, Any]], bool]:
    return lambda row: threshold > 0 and int(row.get("input_tokens") or 0) > threshold


# ── pricing ───────────────────────────────────────────────────────────────────────────────────────────────────


def price_month(groups: Iterable[Mapping[str, Any]], renders: Iterable[Mapping[str, Any]], prices: Sequence[Price],
                since: datetime, bounds: Sequence[datetime],
                jobs: Mapping[str, Mapping[str, Any]] | None = None) -> MonthUsage:
    """Final prices for the month's token groups and renders, by kind and by purpose (`jobs`: the groups' jobs, which
    decide a sheet or a canon refine; renders are scene work)."""
    jobs = jobs or {}
    usage = MonthUsage()
    for g in groups:
        kind = str(g["kind"])
        bucket = costs.BUCKET_OF_KIND[kind]
        at = slot_start(int(g["slot"]), bounds, since)
        row = {"model": g["model"], "input_tokens": int(g["input_tokens"]),
               "image_input_tokens": int(g["image_input_tokens"]),
               "cached_input_tokens": int(g["cached_input_tokens"]),
               "cached_image_input_tokens": int(g.get("cached_image_input_tokens") or 0),
               "output_tokens": int(g["output_tokens"]),
               "created_at": at, "long": bool(g["long"])}
        actual = costs.tokens_actual(row, prices)
        if actual.missing:
            usage.note_missing(str(g["model"]) or "an unnamed model", bucket, int(g["calls"]))
            continue
        part = cost_parts.part_of(str(g.get("phase") or ""), jobs.get(str(g.get("job_id") or "")))
        usage.add(str(g.get("production_id") or ""), bucket, costs.with_margin(actual.micros, kind, at), part)
    for r in renders:
        if not costs.render_billed(r):
            continue
        priced = costs.cost_render(r, prices)
        if priced.missing:
            spec = r.get("spec") or {}
            what = f"{r.get('engine') or spec.get('engine') or 'video'} {spec.get('resolution') or ''}".strip()
            usage.note_missing(what, "video", 1)
            continue
        usage.add(str(r.get("production_id") or ""), "video", priced.micros, "scene")
    return usage


def rows_by_production(usage: MonthUsage) -> list[tuple[str, BucketTotals]]:
    """Productions by total, largest first; calls tied to no production ("") last, only when not zero."""
    named = sorted(((pid, t) for pid, t in usage.productions.items() if pid), key=lambda x: (-x[1].total, x[0]))
    loose = usage.productions.get("")
    return named + ([("", loose)] if loose is not None and loose.total else [])


def by_bucket(missing: Mapping[tuple[str, Bucket], int]) -> list[tuple[str, Bucket, int]]:
    return sorted(((what, bucket, n) for (what, bucket), n in missing.items()), key=lambda x: (-x[2], x[0]))


__all__ = [
    "FIRST_MONTH",
    "BucketTotals",
    "MonthUsage",
    "boundaries",
    "by_bucket",
    "group_rows",
    "long_by_price",
    "long_by_threshold",
    "month_bounds",
    "price_month",
    "rows_by_production",
    "single_long_from",
    "slot_of",
    "slot_start",
]
