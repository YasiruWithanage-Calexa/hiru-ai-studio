"""The wire shapes and the stored result (plan/2026-11-08e phase 1): strict, closed, round-tripping."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from contracts.production import ProductionSettings
from contracts.raphael.bin import Bin, compact
from contracts.raphael.stored import Seconds, StoredRaphael
from contracts.raphael.wire import (
    BLENDS,
    LENGTH_CAPS,
    ClipW,
    ExtrasW,
    ExtraW,
    PutW,
)
from tests.raphael import gold


def _clip_w(**over: object) -> dict:
    row = {
        k: v for k, v in gold.stage1().clips[0].model_dump().items() if k not in ("slate", "stage", "anchor", "blend")
    }
    return {**row, **over}


def test_a_clip_w_holds_the_labs_fields_and_nothing_else() -> None:
    ClipW.model_validate(_clip_w())
    with pytest.raises(ValidationError):
        ClipW.model_validate({**_clip_w(), "stage": 2})


def test_take_priority_and_blend_are_closed_lists() -> None:
    with pytest.raises(ValidationError):
        ClipW.model_validate(_clip_w(take_s=5))
    with pytest.raises(ValidationError):
        # the schema refuses must
        ExtraW.model_validate({**_clip_w(priority="must"), "anchor": ["c01"], "blend": "open"})
    with pytest.raises(ValidationError):
        ExtraW.model_validate({**_clip_w(priority="nice"), "anchor": ["c01"], "blend": "dissolve"})
    for blend in BLENDS:
        ExtraW.model_validate({**_clip_w(priority="nice"), "anchor": ["c01"], "blend": blend})


def test_a_put_and_an_extras_call_hold_a_list_of_clips() -> None:
    assert PutW.model_validate({"clips": [_clip_w()]}).clips[0].id == "c01"
    assert ExtrasW.model_validate({"clips": []}).clips == []


def test_the_gold_bins_load_and_count() -> None:
    first, last = gold.stage1(), gold.final()
    assert first.counts()["clips"] == 13 and first.counts()["take_s"] == 70 and not first.extras()
    assert last.counts()["clips"] == 21 and last.counts()["take_s"] == 112 and len(last.extras()) == 8
    assert all(c.stage == 2 and c.anchor and c.blend in BLENDS for c in last.extras())
    assert compact(last.clips[-1]).startswith("c")


def test_slates_follow_the_setup_and_never_repeat() -> None:
    work = gold.final()
    slates = [c.slate for c in work.clips]
    assert len(set(slates)) == len(slates)
    before = {c.id: c.slate for c in work.clips}
    work.reslate()
    assert {c.id: c.slate for c in work.clips} == before


def test_replace_keeps_id_stage_and_a_must_stays_must() -> None:
    work = gold.final()
    must = work.musts()[0]
    new = work.replace(must.id, ClipW.model_validate(_clip_w(priority="nice")).menu())
    assert new is not None and new.id == must.id and new.priority == "must" and new.stage == 1
    extra = work.extras()[0]
    kept = work.replace(extra.id, ClipW.model_validate(_clip_w(priority="should")).menu())
    assert kept is not None and kept.stage == 2 and kept.anchor == extra.anchor and kept.blend == extra.blend


def test_stored_round_trips_through_json() -> None:
    work = gold.final()
    notes, review = gold.stage2_result()
    stored = StoredRaphael(
        job_id="j1",
        input_hash="abc",
        stage1="finished",
        stage2="finished",
        cap=2,
        edit=work.edit,
        clips=work.clips,
        line_ids={"L4": "x"},
        blend_notes=notes,
        review=review,
        seconds=Seconds(target_s=60, cap_s=120, take_s=112, must_s=70, cinematic_s=42),
    )
    again = StoredRaphael.load(json.loads(json.dumps(stored.data())))
    assert again is not None and again.data() == stored.data()
    assert len(again.extras()) == 8 and len(again.musts()) == 13


def test_stored_load_is_none_for_a_scene_raphael_never_planned() -> None:
    assert StoredRaphael.load({}) is None and StoredRaphael.load(None) is None
    assert StoredRaphael.load({"planner": "jonathan"}) is None
    assert StoredRaphael.load({"planner": "raphael", "cap": 7}) is None


def test_the_length_cap_is_a_setting_with_four_choices() -> None:
    assert ProductionSettings().raphael_length_cap == 2
    assert LENGTH_CAPS == (1.5, 2, 2.5, 3)
    for cap in (1.5, 2, 2.5, 3):
        settings = ProductionSettings.model_validate({"raphael_length_cap": cap, "shot_planner": "raphael"})
        again = ProductionSettings.model_validate(json.loads(settings.model_dump_json()))
        assert again.raphael_length_cap == cap and again.shot_planner == "raphael"
    with pytest.raises(ValidationError):
        ProductionSettings.model_validate({"raphael_length_cap": 4})
    assert ProductionSettings.model_validate({"raphael_length_cap": 2.0}).raphael_length_cap == 2  # JSON gives 2.0 too


def test_a_new_bin_gives_ids_and_slates() -> None:
    work = Bin(scene="12")
    clip = work.add(ClipW.model_validate(_clip_w(setup="b")).menu())
    assert clip.id == "c01" and clip.slate == "12B-1"
