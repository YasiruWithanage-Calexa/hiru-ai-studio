"""contracts.usage_totals (plan/2026-11-23): a month at final prices, by production and bucket. Summed groups priced the
same as every row priced alone, a price or margin change splitting a month, long calls kept apart, video meters left
out, a missing price counted and never zero. No network, no database."""
from __future__ import annotations

import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api import margins as api_margins
from contracts import costs
from contracts import usage_totals as ut
from contracts.costs import SEED_PRICES, Price, cost_render, cost_tokens

SINCE = datetime(2026, 11, 1, tzinfo=UTC)
PRICES = list(SEED_PRICES)


def row(model="gpt-5", phase="shot_producer.craft", i=0, c=0, o=0, at="2026-11-05T00:00:00+00:00", prod="p1",
        **extra):
    return {"production_id": prod, "phase": phase, "model": model, "input_tokens": i, "cached_input_tokens": c,
            "output_tokens": o, "created_at": at, **extra}


def month(rows, renders=(), prices=PRICES):
    bounds = ut.boundaries(prices, costs.margins())
    threshold = ut.single_long_from(prices)
    long = ut.long_by_threshold(threshold) if threshold is not None else ut.long_by_price(prices)
    return ut.price_month(ut.group_rows(rows, bounds, long), renders, prices, SINCE, bounds)


# ── the month ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_month_runs_from_the_first_to_the_next_first_in_utc():
    now = datetime(2026, 11, 23, 8, tzinfo=UTC)
    assert ut.month_bounds(None, now) == ("2026-11", SINCE, datetime(2026, 12, 1, tzinfo=UTC))
    assert ut.month_bounds("2026-12", datetime(2026, 12, 5, tzinfo=UTC))[2] == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["2025-12", "2026-13", "2027-01", "26-11", "2026-1", "november"])
def test_a_month_outside_the_studios_life_is_refused(bad: str):
    with pytest.raises(ValueError):
        ut.month_bounds(bad, datetime(2026, 11, 23, tzinfo=UTC))


def test_slots_count_boundaries_like_postgres_width_bucket():
    b = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 11, 19, tzinfo=UTC)]
    assert ut.slot_of(datetime(2025, 12, 31, tzinfo=UTC), b) == 0
    assert ut.slot_of(datetime(2026, 1, 1, tzinfo=UTC), b) == 1  # a boundary opens its slot
    assert ut.slot_of("2026-11-19T00:00:00+00:00", b) == 2
    assert ut.slot_start(2, b, SINCE) == b[1]
    assert ut.slot_start(1, b, SINCE) == SINCE  # inside the month


# ── buckets ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_three_buckets_at_final_prices():
    text = row(i=1_000_000)  # $1.25 -> llm
    picture = row(model="gpt-image-2", phase="frame_render.image", i=10_000, o=4_000, image_input_tokens=9_000)
    meter = row(model="gemini-omni-1.2-flash", phase="video_render.omni_flash", o=46_336)
    render = {"id": "r1", "production_id": "p1", "status": "done", "engine": "omni_flash",
              "model": "gemini-omni-1.2-flash", "created_at": "2026-11-20T00:00:00+00:00",
              "spec": {"resolution": "720p", "duration_s": 8}, "usage": {"completion_tokens": 46_336}}
    got = month([text, picture, meter], [render])
    assert got.total.llm == cost_tokens(text, PRICES).micros == 1_375_000
    assert got.total.image == cost_tokens(picture, PRICES).micros
    assert got.total.video == cost_render(render, PRICES).micros  # the meter row is NOT counted again
    assert got.total.total == got.total.llm + got.total.image + got.total.video
    assert got.productions["p1"].total == got.total.total


def test_productions_by_total_and_no_production_last():
    got = month([row(i=1_000_000, prod="small"), row(i=9_000_000, prod="big"), row(i=5_000_000, prod=None)])
    order = [pid for pid, _ in ut.rows_by_production(got)]
    assert order == ["big", "small", ""]


def test_unbilled_renders_are_left_out():
    failed = {"production_id": "p1", "status": "failed", "engine": "omni_flash", "model": "gemini-omni-1.2-flash",
              "created_at": "2026-11-20T00:00:00+00:00", "spec": {"resolution": "720p", "duration_s": 8}, "usage": {}}
    assert month([], [failed]).total.total == 0
    assert month([], [failed | {"usage": {"billed": True}}]).total.video == costs.with_margin(8 * 70_000, "video")


def test_a_missing_price_is_counted_not_zeroed_into_the_total():
    got = month([row(model="gpt-9-unknown", i=1_000_000), row(model="gpt-9-unknown", i=5), row(i=1_000_000)])
    assert got.total.llm == 1_375_000
    assert ut.by_bucket(got.missing) == [("gpt-9-unknown", "llm", 2)]
    render = {"production_id": "p1", "status": "done", "engine": "omni_flash", "model": "x",
              "created_at": "2026-11-20T00:00:00+00:00", "spec": {"resolution": "4k", "duration_s": 8}, "usage": {}}
    assert ut.by_bucket(month([], [render]).missing) == [("omni_flash 4k", "video", 1)]


# ── summing is pricing each row ───────────────────────────────────────────────────────────────────────────────


def test_a_thousand_rows_summed_cost_what_they_cost_one_by_one():
    rnd = random.Random(7)  # noqa: S311 - a fixed sample, not a secret
    models = ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-6.1-sol", "gpt-6.1-terra", "text-embedding-3-large"]
    rows = []
    for n in range(1000):
        model = rnd.choice(models)
        i = rnd.choice([rnd.randint(0, 50_000), rnd.randint(272_001, 400_000)])
        rows.append(row(model=model, i=i, c=rnd.randint(0, i // 2), o=rnd.randint(0, 20_000),
                        at=f"2026-11-{rnd.randint(1, 28):02d}T{n % 24:02d}:00:00+00:00",
                        prod=rnd.choice(["p1", "p2", None])))
        if n % 7 == 0:
            rows.append(row(model="gpt-image-2", phase="frame_render.image", i=rnd.randint(500, 9_000),
                            o=rnd.randint(1000, 6000), image_input_tokens=rnd.randint(0, 400),
                            at=f"2026-11-{rnd.randint(1, 28):02d}T00:00:00+00:00"))
    alone = sum(cost_tokens(r, PRICES).micros for r in rows)
    summed = month(rows).total.total
    # each row rounds once for its cost and once for its margin; a group rounds once for both
    assert abs(alone - summed) <= 2 * len(rows)
    assert summed > 0


def test_long_and_short_calls_of_one_model_are_never_summed_together():
    short = [row(model="gpt-6.1-sol", i=200_000) for _ in range(2)]  # 400K summed, each short
    long = [row(model="gpt-6.1-sol", i=300_000)]
    got = month(short + long)
    assert got.total.llm == sum(cost_tokens(r, PRICES).micros for r in short + long)


@pytest.fixture
def later_margin(tmp_path: Path):
    path = tmp_path / "margins.yaml"
    path.write_text("margins:\n  - from: 2026-01-01\n    llm: 10\n    image: 20\n    video: 30\n"
                    "  - from: 2026-11-15\n    llm: 50\n    image: 20\n    video: 30\n",
                    encoding="utf-8")
    costs.use_margins(api_margins.load(path))
    yield
    api_margins.install()


def test_a_margin_change_mid_month_splits_the_month(later_margin):
    rows = [row(i=1_000_000, at="2026-11-10T00:00:00+00:00"), row(i=1_000_000, at="2026-11-20T00:00:00+00:00")]
    assert month(rows).total.llm == 1_375_000 + 1_875_000


def test_a_price_change_mid_month_splits_the_month():
    newer = Price(kind="tokens", model_prefix="gpt-5", input_micros=2_000_000, output_micros=10_000_000,
                  valid_from=datetime(2026, 11, 15, tzinfo=UTC))
    prices = [*PRICES, newer]
    rows = [row(i=1_000_000, at="2026-11-10T00:00:00+00:00"), row(i=1_000_000, at="2026-11-20T00:00:00+00:00")]
    assert month(rows, prices=prices).total.llm == 1_375_000 + 2_200_000


def test_older_picture_rows_sum_as_all_pictures():
    rows = [row(model="gpt-image-2", phase="frame_render.image", i=10_000, o=4_000),
            row(model="gpt-image-2", phase="frame_render.image", i=10_000, o=4_000, image_input_tokens=0)]
    assert month(rows).total.image == sum(cost_tokens(r, PRICES).micros for r in rows)


def test_thresholds_that_differ_are_checked_per_row():
    odd = Price(kind="tokens", model_prefix="gpt-odd", input_micros=1_000_000, long_context_from=100,
                long_input_micros=2_000_000)
    prices = [*PRICES, odd]
    assert ut.single_long_from(prices) is None
    rows = [row(model="gpt-odd", i=150), row(model="gpt-6.1-sol", i=150)]
    assert month(rows, prices=prices).total.llm == sum(cost_tokens(r, prices).micros for r in rows)


def test_cached_pictures_are_split_row_by_row_before_summing():
    """Found on a real Postgres (2026-11-23): one row with text and no cache, one with only cached pictures. Summed
    first, the cache would come off the first row's text at the text rate; each row pays the picture rate."""
    rows = [row(model="gpt-image-2", phase="frame_render.image", i=10_000, image_input_tokens=0),
            row(model="gpt-image-2", phase="frame_render.image", i=10_000, c=8_000, image_input_tokens=10_000)]
    assert month(rows).total.image == sum(cost_tokens(r, PRICES).micros for r in rows)


def test_cached_input_above_the_input_is_capped_row_by_row():
    rows = [row(i=100, c=500), row(i=1_000_000)]
    assert month(rows).total.llm == sum(cost_tokens(r, PRICES).micros for r in rows)
