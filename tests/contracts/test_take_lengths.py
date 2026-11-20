"""plan/2026-11-19: the lengths a production's takes may have, Omni Flash 1.2 only."""
from __future__ import annotations

import pytest

from contracts import take_lengths as tl
from contracts.coverage.scene import Coverage, takes_of
from contracts.production import ProductionSettings, Shot
from contracts.video_gen import ENGINE_CAPABILITIES, VideoOverrides, VideoSettings, describe_spec, engine_label


def test_steps_and_any_length_for_each_maximum() -> None:
    assert tl.take_lengths("steps", 10) == (4, 6, 8, 10)
    assert tl.take_lengths("steps", 15) == (4, 6, 8, 10, 15)  # plan/2026-11-20 D3
    assert tl.take_lengths("any", 10) == tuple(range(3, 11))
    assert tl.take_lengths("any", 15) == tuple(range(3, 16))


def test_a_production_made_before_the_plan_keeps_4_6_8() -> None:
    assert ProductionSettings().takes == (4, 6, 8)
    assert ProductionSettings(take_lengths="any").takes == (4, 6, 8)  # no maximum: the old ladder
    assert ProductionSettings(max_take_s=15, take_lengths="any").takes == tuple(range(3, 16))
    assert ProductionSettings(max_take_s=10, fixed_shot_seconds=6).takes == (6,)


@pytest.mark.parametrize("bad", [{"max_take_s": 12}, {"max_take_s": 8}, {"take_lengths": "free"},
                                 {"fixed_shot_seconds": 2}, {"fixed_shot_seconds": 16}])
def test_settings_outside_the_choices_are_refused(bad: dict) -> None:
    with pytest.raises(ValueError):
        ProductionSettings.model_validate(bad)


def test_a_shot_is_3_to_15_seconds() -> None:
    base = {"id": "00000000-0000-0000-0000-000000000001", "scene_id": "00000000-0000-0000-0000-000000000002",
            "number": 1}
    for seconds in (3, 7, 13, 15):
        assert Shot.model_validate({**base, "duration_s": seconds}).duration_s == seconds
    for seconds in (2, 16):
        with pytest.raises(ValueError):
            Shot.model_validate({**base, "duration_s": seconds})


def test_the_words_for_the_lengths() -> None:
    assert tl.describe((4, 6, 8, 10)) == "4, 6, 8 or 10 s"
    assert tl.describe(tuple(range(3, 16))) == "3 to 15 s"
    assert tl.not_allowed(7, (4, 6, 8, 10)) == "A shot here is 4, 6, 8 or 10 s, not 7 s."
    assert tl.not_allowed(8, (4, 6, 8, 10)) is None


def test_omni_flash_1_2_is_the_only_model_and_makes_3_to_15_s() -> None:
    assert list(ENGINE_CAPABILITIES) == ["omni_flash"]
    cap = ENGINE_CAPABILITIES["omni_flash"]
    assert cap.model == "gemini-omni-1.2-flash" and cap.versions == () and cap.label == "Omni Flash 1.2"
    assert cap.durations == tuple(range(3, 16))


def test_a_stored_veo_or_1_1_choice_reads_as_omni_flash_1_2() -> None:
    v = VideoSettings.model_validate({"engine": "veo_3_1", "resolution": "1080p",
                                      "options": {"person_generation": "allow_all"}})
    assert (v.engine, v.model, v.resolution, v.options) == ("omni_flash", None, "1080p", {})
    assert VideoOverrides.model_validate({"model": "gemini-omni-1.1-flash"}).model is None
    assert ProductionSettings.model_validate({"video": {"engine": "veo_3_1_fast"}}).video.engine == "omni_flash"
    assert engine_label("veo_3_1") == "Veo 3.1" and engine_label("omni_flash") == "Omni Flash 1.2"


def test_an_old_veo_take_keeps_its_name_on_its_card() -> None:
    from contracts.video_gen import RenderSpec

    spec = RenderSpec.model_construct(engine="veo_3_1", model="veo-3.1-generate-preview", resolution="720p",
                                      aspect_ratio="16:9", duration_s=8, draft=False, references=[], seed=None)
    assert describe_spec(spec).startswith("Veo 3.1 · 720p")


def test_coverage_keeps_a_10_s_shot_only_where_the_production_allows_it() -> None:
    scene = {"id": "s1", "heading": "EXT. GATE", "envelope_s": 20, "script": [{"kind": "action", "text": "Waits."}]}
    shot = {"id": "r1", "number": 1, "duration_s": 10, "block_start": 0, "block_end": 1}
    assert Coverage.from_rows(scene, [shot], []).clips[0].take_s == 8  # an old production: 4/6/8
    new = takes_of({"settings": {"max_take_s": 10}})
    cov = Coverage.from_rows(scene, [shot], [], takes=new)
    assert cov.clips[0].take_s == 10 and "A take here is 4, 6, 8 or 10 s." in cov.render()
