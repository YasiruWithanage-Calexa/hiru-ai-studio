"""contracts.costs: micro-dollar money, dated prices, the three margins applied once each, the retry margin on the
to-finish part only, and a missing price as a note (plan/2026-11-06d Phase 1). No network, no database."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts import costs
from contracts.costs import (
    SEED_PRICES,
    Costed,
    Price,
    Tally,
    cost_render,
    cost_tokens,
    estimate_shot_video,
    estimate_unit,
    kind_of,
    median,
    micros_of,
    price_for,
    scene_total,
    tokens_actual,
    with_margin,
    with_retry,
)
from contracts.video_gen import VideoOverrides, VideoSettings, resolve

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 11, 1, tzinfo=UTC)

GPT5 = Price(kind="tokens", model_prefix="gpt-5", input_micros=1_250_000, cached_input_micros=125_000,
             output_micros=10_000_000, valid_from=T0)
MINI = Price(kind="tokens", model_prefix="gpt-5-mini", input_micros=250_000, cached_input_micros=25_000,
             output_micros=2_000_000, valid_from=T0)
IMG = Price(kind="tokens", model_prefix="gpt-image-2", input_micros=8_000_000, cached_input_micros=2_000_000,
            output_micros=30_000_000, valid_from=T0)
OMNI = Price(kind="video_second", engine="omni_flash", resolution="720p", per_second_micros=100_000, valid_from=T0)
PRICES = [GPT5, MINI, IMG, OMNI]


def row(model="gpt-5", phase="shot_producer.craft", i=0, c=0, o=0, at="2026-11-02T00:00:00+00:00"):
    return {"model": model, "phase": phase, "input_tokens": i, "cached_input_tokens": c, "output_tokens": o,
            "created_at": at}


# ── money ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_micros_of_is_exact_decimal_math():
    assert micros_of("1.25") == 1_250_000
    assert micros_of("0.005") == 5_000
    assert micros_of("10") == 10_000_000
    assert micros_of("0.40") == 400_000


def test_a_gpt5_call_is_priced_per_million_tokens():
    # 600k fresh at 1.25 + 400k cached at 0.125 + 100k out at 10 = 0.75 + 0.05 + 1.00
    got = tokens_actual(row(i=1_000_000, c=400_000, o=100_000), PRICES)
    assert got == Costed(1_800_000)


def test_output_tokens_already_include_reasoning_and_are_not_added_again():
    r = row(i=0, o=1_000_000) | {"reasoning_tokens": 900_000}
    assert tokens_actual(r, PRICES).micros == 10_000_000


def test_sums_are_integers_never_floats():
    total = Tally().extend(cost_tokens(row(i=1, o=1), PRICES) for _ in range(1000))
    assert isinstance(total.micros, int)


# ── prices: longest prefix, dated ─────────────────────────────────────────────────────────────────────────────


def test_longest_model_prefix_wins():
    assert price_for("tokens", {"model": "gpt-5-mini-2026"}, T0, PRICES) is MINI
    assert price_for("tokens", {"model": "gpt-5-2025-08-07"}, T0, PRICES) is GPT5  # a dated snapshot
    assert price_for("tokens", {"model": "GPT-5-MINI"}, T0, PRICES) is MINI


def test_a_different_model_that_merely_starts_with_a_name_is_not_priced_as_it():
    assert price_for("tokens", {"model": "gpt-5.5"}, T0, PRICES) is None  # not gpt-5: the lab billed it so once
    assert price_for("tokens", {"model": "gpt-5.5"}, T0, SEED_PRICES).input_micros == 5_000_000
    assert price_for("tokens", {"model": "gpt-6.1-sol"}, T0, SEED_PRICES).output_micros == 10_000_000


def test_a_price_applies_only_from_its_date():
    new = GPT5.model_copy(update={"input_micros": 2_000_000, "valid_from": datetime(2026, 11, 10, tzinfo=UTC)})
    both = [GPT5, new]
    old_row = row(i=1_000_000, at="2026-11-05T00:00:00+00:00")
    new_row = row(i=1_000_000, at="2026-11-11T00:00:00+00:00")
    assert tokens_actual(old_row, both).micros == 1_250_000  # old spending keeps the price it was made at
    assert tokens_actual(new_row, both).micros == 2_000_000


def test_no_price_before_its_first_date():
    assert price_for("tokens", {"model": "gpt-5"}, datetime(2026, 10, 1, tzinfo=UTC), PRICES) is None


def test_a_missing_price_is_a_note_not_zero_and_not_a_guess():
    got = cost_tokens(row(model="gpt-6.1-sol", i=1000, o=1000), PRICES)
    assert got.micros == 0
    assert got.missing == ("no price for gpt-6.1-sol",)


def test_video_price_prefers_the_named_model():
    generic = Price(kind="video_second", engine="veo_3_1", resolution="1080p", per_second_micros=400_000,
                    valid_from=T0)
    named = Price(kind="video_second", engine="veo_3_1", model="veo-3.1-x", resolution="1080p",
                  per_second_micros=500_000, valid_from=T0)
    keys = {"engine": "veo_3_1", "model": "veo-3.1-x", "resolution": "1080p"}
    assert price_for("video_second", keys, T0, [generic, named]) is named
    assert price_for("video_second", {**keys, "model": "other"}, T0, [generic, named]) is generic
    assert price_for("video_second", {**keys, "resolution": "720p"}, T0, [generic, named]) is None


# ── margins: 5% on images, 10% on video, 0 on text, each exactly once ─────────────────────────────────────────


def test_margin_table():
    assert costs.MARGIN == {"text": 0, "image": 500, "video": 1000}
    assert costs.RETRY_MARGIN == 2000


def test_with_margin_rounds_half_up():
    assert with_margin(1_000_000, "video") == 1_100_000
    assert with_margin(1_000_000, "image") == 1_050_000
    assert with_margin(1_000_000, "text") == 1_000_000
    assert with_margin(5, "image") == 5  # 5.25 -> 5
    assert with_margin(10, "image") == 11  # 10.5 -> 11
    assert with_retry(1_000_000) == 1_200_000


def test_a_text_call_has_no_margin():
    assert cost_tokens(row(i=1_000_000), PRICES).micros == 1_250_000


def test_a_picture_gets_the_image_margin_once():
    r = row(model="gpt-image-2", phase="frame_render.image", i=100_000, o=10_000)  # 0.8 + 0.3 = 1.1
    assert tokens_actual(r, PRICES).micros == 1_100_000
    assert cost_tokens(r, PRICES).micros == 1_155_000


def test_a_video_meter_row_is_not_priced_as_text():
    meter = row(model="gemini-omni-1.1-flash", phase="video_render.omni_flash", o=5792 * 8)
    assert kind_of(meter["phase"]) == "metered"
    assert cost_tokens(meter, PRICES) == Costed()


def test_a_render_is_seconds_times_price_with_the_video_margin():
    render = {"status": "done", "engine": "omni_flash", "model": "gemini-omni-1.1-flash", "created_at": T0.isoformat(),
              "spec": {"resolution": "720p", "duration_s": 8}, "usage": {"seconds_rendered": 8, "takes_made": 1}}
    assert cost_render(render, PRICES).micros == 880_000  # 8 s x $0.10 x 1.10
    assert costs.video_actual(render, PRICES).micros == 800_000


def test_a_render_falls_back_to_the_spec_length_and_counts_takes():
    render = {"status": "done", "engine": "omni_flash", "model": "m", "created_at": T0.isoformat(),
              "spec": {"resolution": "720p", "duration_s": 6}, "usage": {"takes_made": 2}}
    assert costs.video_actual(render, PRICES).micros == 1_200_000


def test_failed_and_refused_renders_count_only_when_the_provider_billed_them():
    base = {"engine": "omni_flash", "model": "m", "created_at": T0.isoformat(),
            "spec": {"resolution": "720p", "duration_s": 4}}
    assert cost_render({**base, "status": "failed", "usage": {}}, PRICES) == Costed()
    assert cost_render({**base, "status": "queued", "usage": {}}, PRICES) == Costed()
    assert cost_render({**base, "status": "refused", "usage": {"billed": True}}, PRICES).micros == 440_000


def test_a_render_without_a_price_is_reported_and_left_out():
    render = {"status": "done", "engine": "omni_flash", "model": "m", "created_at": T0.isoformat(),
              "spec": {"resolution": "1080p", "duration_s": 4}, "usage": {}}
    got = cost_render(render, PRICES)
    assert got.micros == 0 and got.missing == ("no price for omni_flash at 1080p",)


# ── the estimate equals resolve()'s seconds x takes ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("seconds", [4, 6, 8])
def test_estimate_uses_what_resolve_gives_and_the_video_margin(seconds):
    resolved = resolve(VideoSettings(), None, None, production_aspect="16:9", shot_seconds=seconds)
    got = estimate_shot_video(resolved, PRICES, T0)
    assert got.micros == with_margin(resolved.duration_s * resolved.takes * 100_000, "video")


def test_estimate_follows_a_shots_own_length_override():
    resolved = resolve(VideoSettings(), VideoOverrides(duration_s=8), None, production_aspect="16:9", shot_seconds=4)
    assert estimate_shot_video(resolved, PRICES, T0).micros == 880_000


def test_estimate_without_a_price_says_so():
    resolved = resolve(VideoSettings(resolution="1080p"), None, None, production_aspect="16:9", shot_seconds=4)
    got = estimate_shot_video(resolved, PRICES, T0)
    assert got.micros == 0 and got.missing


def test_unit_estimates_carry_their_kind_margin():
    assert estimate_unit("frame", SEED_PRICES, T0).micros == with_margin(80_000, "image")
    assert estimate_unit("prompt", SEED_PRICES, T0).micros == 20_000
    assert estimate_unit("frame", [], T0).missing == ("no estimate price for a frame",)


def test_median_is_a_whole_number():
    assert median([]) is None
    assert median([5]) == 5
    assert median([9, 1, 5]) == 5
    assert median([1, 2, 3, 4]) == 2


# ── a scene's total ───────────────────────────────────────────────────────────────────────────────────────────


def test_retry_margin_applies_to_the_to_finish_part_only():
    total = scene_total([Costed(6_120_000)], [Costed(12_280_000)])
    assert total.spent_micros == 6_120_000
    assert total.to_finish_micros == 12_280_000
    assert total.total_micros == 6_120_000 + 14_736_000  # the plan's example, to the cent: $20.86
    assert round(total.total_micros / 10_000) == 2086


def test_retry_margin_comes_after_the_kind_margins_not_before():
    video = Costed(with_margin(1_000_000, "video"))  # 1.10
    assert scene_total([], [video]).total_micros == with_retry(1_100_000) == 1_320_000  # not 1.0 x 1.2 x 1.1 re-rounded


def test_an_empty_scene_costs_nothing_and_is_complete():
    total = scene_total([], [])
    assert (total.total_micros, total.complete, total.missing) == (0, True, ())


def test_a_missing_price_makes_the_total_incomplete_but_keeps_the_rest():
    total = scene_total([Costed(1_000_000, ("no price for x",))], [Costed(500_000, ("no price for x",))])
    assert total.complete is False
    assert total.missing == ("no price for x",)
    assert total.total_micros == 1_000_000 + 600_000


# ── the closed list of phases ─────────────────────────────────────────────────────────────────────────────────

_IMAGE_WORDS = re.compile(r"(image|images|sheet|sheets|picture|pictures|paint|painter)$", re.I)  # the last segment


def _declared_phases() -> set[str]:
    out: set[str] = set()
    for path in (ROOT / "src" / "libs" / "hiru_ai").rglob("component.yaml"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*phase:\s*([\w.]+)", line)
            if m:
                out.add(m.group(1))
    return out


def test_no_declared_model_phase_looks_like_a_picture_unless_it_is_listed():
    suspicious = {p for p in _declared_phases() if _IMAGE_WORDS.search(p) and p not in costs.IMAGE_PHASES}
    assert suspicious == set(), f"priced as text but named like a picture: add to IMAGE_PHASES? {sorted(suspicious)}"


def test_every_listed_image_phase_is_priced_as_an_image():
    assert all(kind_of(p) == "image" for p in costs.IMAGE_PHASES)
    assert kind_of("frame_render.vision") == "text"


# ── the seeded prices ─────────────────────────────────────────────────────────────────────────────────────────


def test_seeded_prices_cover_the_models_the_repo_uses():
    for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "text-embedding-3-large", "gpt-image-2"):
        assert price_for("tokens", {"model": model}, datetime.now(UTC), SEED_PRICES) is not None, model
    for engine, res in (("omni_flash", "720p"), ("veo_3_1", "720p"), ("veo_3_1", "1080p")):
        assert price_for("video_second", {"engine": engine, "model": "x", "resolution": res},
                         datetime.now(UTC), SEED_PRICES) is not None


def test_the_migration_seeds_exactly_the_code_prices():
    sql = (ROOT / "Database" / "upgrade_v16_to_v17.sql").read_text(encoding="utf-8")
    for p in SEED_PRICES:
        key = p.model_prefix or p.engine
        assert f"'{key}'" in sql, key
        for value in (p.input_micros, p.output_micros, p.per_second_micros, p.unit_micros):
            if value:
                assert str(value) in sql, (key, value)
