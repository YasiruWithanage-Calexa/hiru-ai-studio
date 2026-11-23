"""contracts.costs: micro-dollar money, dated prices, the three margins (from margins.yaml, dated) applied once
each, no retry margin (plan/2026-11-23b), a missing price as a note (plan/2026-11-06d Phase 1), and the price
shapes of plan/2026-11-23: picture input, long context, Omni by its tokens. No network, no database."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api import margins as api_margins
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


# ── margins (margins.yaml): llm 10 %, image 20 %, video 30 %, each exactly once; no retry margin ───────────────


def test_the_margins_file_is_the_persons_table():
    m = api_margins.load()
    assert [e.bp for e in m.entries] == [{"llm": 1000, "image": 2000, "video": 3000}]
    assert m.entries[0].start == datetime(2026, 1, 1, tzinfo=UTC)


def test_with_margin_rounds_half_up():
    assert with_margin(1_000_000, "video") == 1_300_000
    assert with_margin(1_000_000, "image") == 1_200_000
    assert with_margin(1_000_000, "text") == 1_100_000
    assert with_margin(1_000_000, "llm") == 1_100_000
    assert with_margin(4, "text") == 4  # 4.4 -> 4
    assert with_margin(15, "text") == 17  # 16.5 -> 17


def test_a_text_call_gets_the_llm_margin_once():
    assert cost_tokens(row(i=1_000_000), PRICES).micros == 1_375_000


def test_a_picture_gets_the_image_margin_once():
    r = row(model="gpt-image-2", phase="frame_render.image", i=100_000, o=10_000)  # 0.8 + 0.3 = 1.1
    assert tokens_actual(r, PRICES).micros == 1_100_000
    assert cost_tokens(r, PRICES).micros == 1_320_000


def test_a_video_meter_row_is_not_priced_as_text():
    meter = row(model="gemini-omni-1.1-flash", phase="video_render.omni_flash", o=5792 * 8)
    assert kind_of(meter["phase"]) == "metered"
    assert cost_tokens(meter, PRICES) == Costed()


def test_a_render_is_seconds_times_price_with_the_video_margin():
    render = {"status": "done", "engine": "omni_flash", "model": "gemini-omni-1.1-flash", "created_at": T0.isoformat(),
              "spec": {"resolution": "720p", "duration_s": 8}, "usage": {"seconds_rendered": 8, "takes_made": 1}}
    assert cost_render(render, PRICES).micros == 1_040_000  # 8 s x $0.10 x 1.30
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
    assert cost_render({**base, "status": "refused", "usage": {"billed": True}}, PRICES).micros == 520_000


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
    assert estimate_shot_video(resolved, PRICES, T0).micros == 1_040_000


def test_estimate_without_a_price_says_so():
    resolved = resolve(VideoSettings(resolution="1080p"), None, None, production_aspect="16:9", shot_seconds=4)
    got = estimate_shot_video(resolved, PRICES, T0)
    assert got.micros == 0 and got.missing


def test_unit_estimates_carry_their_kind_margin():
    assert estimate_unit("frame", SEED_PRICES, T0).micros == with_margin(80_000, "image")
    assert estimate_unit("prompt", SEED_PRICES, T0).micros == 22_000  # plan/2026-11-20d D12, + the llm margin
    assert estimate_unit("frame", [], T0).missing == ("no estimate price for a frame",)


def test_median_is_a_whole_number():
    assert median([]) is None
    assert median([5]) == 5
    assert median([9, 1, 5]) == 5
    assert median([1, 2, 3, 4]) == 2


# ── a scene's total ───────────────────────────────────────────────────────────────────────────────────────────


def test_a_scene_is_spent_plus_what_is_left_with_no_retry_margin():
    total = scene_total([Costed(6_120_000)], [Costed(12_280_000)])
    assert total.spent_micros == 6_120_000
    assert total.to_finish_micros == 12_280_000
    assert total.total_micros == 6_120_000 + 12_280_000  # plan/2026-11-23b: no x1.2 on the part left to make


def test_the_kind_margin_is_the_only_margin_on_what_is_left():
    video = Costed(with_margin(1_000_000, "video"))  # 1.30
    assert scene_total([], [video]).total_micros == 1_300_000


def test_an_empty_scene_costs_nothing_and_is_complete():
    total = scene_total([], [])
    assert (total.total_micros, total.complete, total.missing) == (0, True, ())


def test_a_missing_price_makes_the_total_incomplete_but_keeps_the_rest():
    total = scene_total([Costed(1_000_000, ("no price for x",))], [Costed(500_000, ("no price for x",))])
    assert total.complete is False
    assert total.missing == ("no price for x",)
    assert total.total_micros == 1_000_000 + 500_000


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


def test_the_migrations_seed_exactly_the_code_prices():
    """Every code price is in the database once v17 and v29 are applied (v29 adds and corrects; rows are never
    edited), with every one of its numbers."""
    sql = "".join((ROOT / "Database" / f).read_text(encoding="utf-8")
                  for f in ("upgrade_v16_to_v17.sql", "upgrade_v28_to_v29.sql"))
    for p in SEED_PRICES:
        key = p.model or p.model_prefix or p.engine
        assert f"'{key}'" in sql, key
        for value in (p.input_micros, p.output_micros, p.per_second_micros, p.unit_micros, p.image_input_micros,
                      p.cached_image_input_micros, p.text_output_micros, p.long_input_micros,
                      p.long_cached_input_micros, p.long_output_micros):
            if value:
                assert str(value) in sql, (key, value)


def test_v30_only_regroups_the_month_function_and_v29_stays_as_applied():
    """The person applied upgrade_v28_to_v29.sql; plan/2026-11-23b's change is a new upgrade, never an edit of it."""
    v29 = (ROOT / "Database" / "upgrade_v28_to_v29.sql").read_text(encoding="utf-8")
    v30 = (ROOT / "Database" / "upgrade_v29_to_v30.sql").read_text(encoding="utf-8")
    full = (ROOT / "Database" / "schema_v30.sql").read_text(encoding="utf-8")
    assert "phase text, job_id uuid" not in v29 and "create or replace function public.token_usage_totals" in v29
    assert "drop function if exists public.token_usage_totals" in v30 and "phase text, job_id uuid" in v30
    assert "alter table" not in v30 and "insert into" not in v30
    assert "phase text, job_id uuid" in full and full.count("create function public.token_usage_totals") == 1


def test_schema_v29_is_v28_plus_the_upgrade():
    full = (ROOT / "Database" / "schema_v29.sql").read_text(encoding="utf-8")
    for needle in ("image_input_tokens integer", "'video_tokens'", "long_context_from", "token_usage_totals",
                   "'gemini-omni-1.2-flash'", "grant execute on function public.token_usage_totals"):
        assert needle in full, needle


# ── plan/2026-11-23: the margins file ─────────────────────────────────────────────────────────────────────────

GOOD = """margins:
  - from: 2026-01-01
    llm: 10
    image: 20
    video: 30
"""


def _file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "margins.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_margins_file_is_an_error_never_zero(tmp_path: Path):
    with pytest.raises(costs.MarginsError, match="missing"):
        api_margins.load(tmp_path / "nope.yaml")


@pytest.mark.parametrize(("text", "fault"), [
    (GOOD.replace("    video: 30\n", ""), "missing video"),
    (GOOD.replace("llm: 10", "llm: -5"), "percent"),
    (GOOD.replace("llm: 10", "llm: 10.125"), "two decimals"),
    (GOOD.replace("llm: 10", "llm: 501"), "above 500"),
    (GOOD.replace("llm: 10", "llm: ten"), "percent"),
    (GOOD.replace("from: 2026-01-01", "from: soon"), "date"),
    (GOOD.replace("    llm: 10\n", "    llm: 10\n    lmm: 1\n"), "unknown"),
    (GOOD + "  - from: 2025-01-01\n    llm: 1\n    image: 1\n    video: 1\n", "later"),
    (GOOD + "extra: 1\n", "unknown keys"),
    (GOOD + "estimate:\n  retry: 20\n", "no retry margin"),
    ("margins: []\n", "non-empty"),
    ("margins: [\n", "YAML"),
])
def test_a_broken_margins_file_says_what_is_wrong(tmp_path: Path, text: str, fault: str):
    with pytest.raises(costs.MarginsError, match=fault):
        api_margins.load(_file(tmp_path, text))


def test_a_percent_with_decimals_is_exact_basis_points(tmp_path: Path):
    m = api_margins.load(_file(tmp_path, GOOD.replace("llm: 10", "llm: 12.5").replace("image: 20", "image: 0")))
    assert m.at("llm") == 1250 and m.at("text") == 1250 and m.at("image") == 0


@pytest.fixture
def two_margins(tmp_path: Path):
    """10/20/30 from 2026-01-01, then 15/25/35 from 2026-11-15."""
    text = GOOD + "  - from: 2026-11-15\n    llm: 15\n    image: 25\n    video: 35\n"
    costs.use_margins(api_margins.load(_file(tmp_path, text)))
    yield
    api_margins.install()


def test_a_margin_change_never_reprices_work_made_before_it(two_margins):
    before = row(i=1_000_000, at="2026-11-10T00:00:00+00:00")
    after = row(i=1_000_000, at="2026-11-16T00:00:00+00:00")
    assert cost_tokens(before, PRICES).micros == 1_375_000  # 1.25 x 1.10
    assert cost_tokens(after, PRICES).micros == 1_437_500  # 1.25 x 1.15
    render = {"status": "done", "engine": "omni_flash", "model": "m", "created_at": "2026-11-16T00:00:00+00:00",
              "spec": {"resolution": "720p", "duration_s": 8}, "usage": {"seconds_rendered": 8}}
    assert cost_render(render, PRICES).micros == 1_080_000  # 0.80 x 1.35


def test_pricing_before_the_margins_are_installed_is_an_error_never_zero():
    costs.use_margins(None)
    with pytest.raises(costs.MarginsError, match="not loaded"):
        with_margin(1_000_000, "video")


def test_the_api_reads_the_margins_file_contracts_never_does():
    # contracts stays free of YAML (tests/test_isolation.py checks every import); the file lives with the API
    assert api_margins.MARGINS_FILE == ROOT / "src" / "api" / "margins.yaml"
    assert api_margins.MARGINS_FILE.is_file()


def test_work_older_than_the_first_entry_still_gets_a_margin():
    assert costs.margins().at("video", datetime(2025, 6, 1, tzinfo=UTC)) == 3000


# ── plan/2026-11-23: picture input, long context ──────────────────────────────────────────────────────────────


def test_pictures_sent_in_cost_more_than_text():
    seed = list(SEED_PRICES)
    # 1,000 text + 9,000 pictures in, 4,000 out: 1000 x 5 + 9000 x 8 + 4000 x 30 = 0.005 + 0.072 + 0.12
    r = row(model="gpt-image-2", phase="frame_render.image", i=10_000, o=4_000) | {"image_input_tokens": 9_000}
    assert tokens_actual(r, seed).micros == 197_000


def test_an_older_picture_row_is_priced_as_all_pictures_as_before():
    seed = list(SEED_PRICES)
    r = row(model="gpt-image-2", phase="frame_render.image", i=10_000, o=4_000)  # no image_input_tokens
    assert tokens_actual(r, seed).micros == 200_000  # 10,000 x 8.00 + 4,000 x 30.00 = 0.08 + 0.12


def test_cached_tokens_come_off_the_text_first():
    seed = list(SEED_PRICES)
    # text 1,000 (cached 1,000 at 1.25), pictures 9,000 (cached 500 at 2.00, 8,500 at 8.00)
    r = row(model="gpt-image-2", phase="frame_render.image", i=10_000, c=1_500) | {"image_input_tokens": 9_000}
    assert tokens_actual(r, seed).micros == 70_250  # 0.00125 + 0.001 + 0.068


def test_a_long_call_is_billed_at_the_long_rates():
    seed = list(SEED_PRICES)
    short = row(model="gpt-6.1-sol", i=272_000, o=1_000)
    long = row(model="gpt-6.1-sol", i=272_001, o=1_000)
    assert tokens_actual(short, seed).micros == 272_000 * 2 + 1_000 * 10  # 0.544 + 0.010
    assert tokens_actual(long, seed).micros == 272_001 * 4 + 1_000 * 15
    assert tokens_actual(row(model="gpt-5", i=400_000), seed).micros == 500_000  # gpt-5 has no long tier


def test_a_summed_group_says_long_itself():
    seed = list(SEED_PRICES)
    group = row(model="gpt-6.1-sol", i=500_000) | {"long": False}  # two short calls summed past 272K
    assert tokens_actual(group, seed).micros == 1_000_000


# ── plan/2026-11-23: Omni by its tokens ───────────────────────────────────────────────────────────────────────


def _omni(usage: dict, model: str = "gemini-omni-1.2-flash", resolution: str = "720p") -> dict:
    return {"status": "done", "engine": "omni_flash", "model": model, "created_at": "2026-11-20T00:00:00+00:00",
            "spec": {"resolution": resolution, "duration_s": 8}, "usage": {"seconds_rendered": 8, **usage}}


def test_omni_is_priced_by_the_tokens_it_reported():
    seed = list(SEED_PRICES)
    render = _omni({"prompt_tokens": 2_000, "completion_tokens": 47_336, "video_tokens": 46_336,
                    "thought_tokens": 1_000})
    # 2,000 x 1.50 + 46,336 x 12 + 1,000 x 9 = 0.003 + 0.556032 + 0.009
    assert costs.video_actual(render, seed).micros == 568_032
    assert cost_render(render, seed).micros == with_margin(568_032, "video")


def test_an_omni_render_before_the_split_is_all_video_tokens():
    seed = list(SEED_PRICES)
    render = _omni({"prompt_tokens": 0, "completion_tokens": 46_336})
    assert costs.video_actual(render, seed).micros == 556_032


def test_an_omni_render_without_tokens_falls_back_to_googles_per_second_rate():
    seed = list(SEED_PRICES)
    assert costs.video_actual(_omni({}), seed).micros == 8 * 70_000
    assert costs.video_actual(_omni({}, resolution="360p"), seed).micros == 8 * 23_000
    assert costs.video_actual(_omni({}, resolution="1080p"), seed).micros == 8 * 104_000


def test_a_retired_omni_11_render_keeps_its_own_price():
    seed = list(SEED_PRICES)
    old = _omni({"completion_tokens": 46_336}, model="gemini-omni-1.1-flash")
    assert costs.video_actual(old, seed).micros == 8 * 100_000


def test_a_scene_estimate_uses_omni_12s_per_second_rate():
    resolved = resolve(VideoSettings(), None, None, production_aspect="16:9", shot_seconds=8)
    got = estimate_shot_video(resolved, SEED_PRICES)
    assert got.micros == with_margin(resolved.duration_s * resolved.takes * 70_000, "video")


def test_every_model_the_product_calls_has_a_price():
    for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.5", "gpt-6.1-sol", "gpt-6.1-terra",
                  "text-embedding-3-large", "text-embedding-3-small", "gpt-image-2"):
        assert price_for("tokens", {"model": model}, None, SEED_PRICES) is not None, model
    assert price_for("video_tokens", {"model": "gemini-omni-1.2-flash"}, None, SEED_PRICES) is not None
