"""contracts.adam: the plan as typed data and its mapping onto the existing `shots` row (plan/2026-11-04b §5.1)."""
from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError
from tests.adam import gold

from contracts.adam import mapping, plan, tiers
from contracts.adam.plan import AdamPlan, Moment, ShotCard, block_of, block_ref

FRAMINGS_IN_THE_DATABASE = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")  # shots.framing check


def test_the_framing_values_are_the_shots_tables():
    assert mapping.FRAMINGS == FRAMINGS_IN_THE_DATABASE


@pytest.mark.parametrize(("size", "arrangement", "framing"), [
    ("ECU", "single", "CU"), ("CU", "single", "CU"), ("MCU", "single", "MCU"), ("MS", "single", "MS"),
    ("EWS", "single", "WIDE"), ("WS", "single", "WIDE"), ("MWS", "single", "WIDE"),
    ("MWS", "two", "TWO"), ("MS", "ots", "OTS"), ("MCU", "pov", "MCU"), ("WS", "group", "WIDE"),
    ("INSERT", "single", "INSERT"), ("INSERT", "pov", "INSERT"), ("INSERT", "two", "INSERT"),
])
def test_size_and_arrangement_map_onto_the_seven_framings(size: str, arrangement: str, framing: str):
    assert mapping.framing_of(size, arrangement) == framing
    assert framing in FRAMINGS_IN_THE_DATABASE


def test_every_size_and_arrangement_maps_to_a_framing_the_database_accepts():
    for size in plan.SIZES:
        for arrangement in ("single", "two", "ots", "pov", "group"):
            assert mapping.framing_of(size, arrangement) in FRAMINGS_IN_THE_DATABASE


def test_a_card_becomes_a_shots_row():
    adam = AdamPlan.model_validate(gold.master("phone_call"))
    card = adam.cards[6]  # card 7: the turn, 8 s, CU, push-in
    row = mapping.card_to_row(card, adam.moments)
    assert row["number"] == 7 and row["framing"] == "CU" and row["duration_s"] == 8
    assert (row["block_start"], row["block_end"]) == (4, 6)  # the script blocks 4 and 5; end is exclusive
    assert row["camera_link"] == "cut" and row["planner"] == "adam"
    assert row["card"]["rhythm_break"] is False and row["card"]["focus"]["from"] == "Dasun"
    json.dumps(row)  # the whole row is JSON: it goes in shots.card


def test_a_card_whose_moments_name_no_block_keeps_the_fallback_range():
    adam = AdamPlan.model_validate(gold.master("phone_call"))
    card = ShotCard(number=1, moments=["nope"], size="CU", take_s=4)
    assert mapping.block_range(card, adam.moments, fallback=(3, 4)) == (3, 4)


def test_the_first_and_last_card_cover_the_whole_script():
    adam = AdamPlan.model_validate(gold.master("phone_call"))
    rows = [mapping.card_to_row(c, adam.moments) for c in adam.cards]
    assert rows[0]["block_start"] == 0 and rows[-1]["block_end"] == 10


def test_the_card_round_trips_through_json():
    adam = AdamPlan.model_validate(gold.master("phone_call"))
    again = AdamPlan.model_validate(adam.model_dump(mode="json", by_alias=True))
    assert again == adam


def test_the_plan_models_forbid_fields_they_do_not_know():
    with pytest.raises(ValidationError):
        ShotCard.model_validate({"number": 1, "moments": [], "size": "CU", "take_s": 4, "mood": "sad"})
    with pytest.raises(ValidationError):
        Moment.model_validate({"id": "m 1", "tier": "script"})  # an id has no spaces


def test_a_moment_tier_is_normalised_and_invention_can_be_named():
    assert Moment.model_validate({"id": "m1", "tier": " Script "}).tier == "script"
    assert Moment.model_validate({"id": "m1", "tier": "invention"}).tier == "invention"
    with pytest.raises(ValidationError):
        Moment.model_validate({"id": "m1", "tier": "dream"})


def test_blocks_are_named_b_and_a_number():
    assert block_ref(3) == "b3" and block_of("b3") == 3 and block_of("m3") is None
    assert Moment.model_validate({"id": "m1", "tier": "script", "serves": ["b2", "b3", "m9"]}).blocks == [2, 3]


def test_the_tiers_and_the_allowed_elaborations_are_the_plans():
    assert tiers.ALLOWED_TIERS == ("script", "implied", "elaboration") and "invention" in tiers.TIERS
    assert set(tiers.ELABORATION_KINDS) == {
        "baseline", "reaction", "listener", "insert_detail", "hands", "pov", "atmosphere", "hold", "plant",
        "transition", "empty_frame", "implied_action", "move"}  # §6.1, thirteen kinds
    assert tiers.NEEDS_WHO <= set(tiers.ELABORATION_KINDS) and tiers.NEEDS_OBJECTS <= set(tiers.ELABORATION_KINDS)


def test_the_plan_reads_a_payload_whole_or_in_parts():
    raw = gold.master("phone_call")
    assert len(plan.moments_of({"plan": raw})) == len(plan.moments_of({"moments": raw["moments"]})) == 17
    assert len(plan.cards_of({"plan": raw})) == 13
    scene = plan.scene_of({"scene": gold.scene("phone_call")})
    assert len(scene.lines) == 4 and scene.block(2) is not None and scene.block(99) is None


def test_the_analysis_accepts_break_by_its_script_name():
    raw: dict[str, Any] = gold.master("phone_call")["analysis"]
    analysis = plan.SceneAnalysis.model_validate(raw)
    assert analysis.break_.block == 4
    assert analysis.model_dump(by_alias=True)["break"]["block"] == 4


def test_the_contracts_use_the_veo_clock_not_their_own():
    from contracts import timing

    assert timing.WORDS_PER_SECOND == 2.2  # one source of truth; adam_fit imports it
