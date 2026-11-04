"""adam_trim and the editorial plan: a 2 s reaction cut from a 4 s take, a pre-lap, never a word (Phase 9)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.adam.editorial import CARRY_S, PRE_LAP_S, plan_cuts, propose_trims, runtime_s
from contracts.adam.plan import ShotCard
from hiru_ai.steps.adam.adam_trim import step

HERE = Path(__file__).resolve().parents[1]


def card(number: int, take: int = 4, **extra: Any) -> ShotCard:
    return ShotCard.model_validate({"number": number, "moments": [f"m{number}"], "size": "CU", "take_s": take, **extra})


def reaction(number: int = 1, **extra: Any) -> ShotCard:
    return card(number, beats=[{"window": [0, 2], "action": "he reads her face"}], **extra)


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["cards"][0]["use_s"] == 2.0 and out["cards"][1].get("use_s") is None and out["saved_s"] == 2.0


def test_a_two_second_reaction_is_cut_from_a_four_second_take():
    trimmed, notes = propose_trims([reaction(1), card(2)])
    assert (trimmed[0].use_s, trimmed[0].in_s) == (2.0, 0.0) and notes == ["card 1: keep 2 s from 0 s of the 4 s take"]
    assert plan_cuts(trimmed, editorial=True)[0].use_s == 2.0 and runtime_s(plan_cuts(trimmed, editorial=True)) == 6.0


def test_with_trimming_off_every_take_plays_whole_and_nothing_is_laid_across_a_cut():
    trimmed, _ = propose_trims([reaction(1, sound={"pre_lap": "the ring"}), card(2)])
    clips = plan_cuts(trimmed, editorial=False)
    assert [(c.use_s, c.lead_s, c.tail_s) for c in clips] == [(4.0, 0.0, 0.0), (4.0, 0.0, 0.0)]


def test_a_card_with_words_the_last_shot_and_the_one_break_are_never_trimmed():
    cards = [reaction(1, lines=[{"line_id": "L1"}]), reaction(2, rhythm_break=True), reaction(3)]
    trimmed, notes = propose_trims(cards)
    assert notes == [] and all(c.use_s is None for c in trimmed)


def test_a_trim_that_saves_less_than_a_second_is_not_made():
    trimmed, _ = propose_trims([card(1, 6, beats=[{"window": [0, 5.5], "action": "x"}]), card(2)])
    assert trimmed[0].use_s is None


def test_a_pre_lap_starts_the_kept_part_late_so_its_sound_can_arrive_early():
    trimmed, _ = propose_trims([card(1, 6, beats=[{"window": [0, 2], "action": "x"}], sound={"pre_lap": "the buzz"}),
                                card(2)])
    assert trimmed[0].in_s == PRE_LAP_S
    clip = plan_cuts(trimmed, editorial=True)[0]
    assert (clip.in_s, clip.lead_s, clip.start_s) == (PRE_LAP_S, PRE_LAP_S, 0.0)


def test_a_pre_lap_with_no_take_to_spare_gets_none_and_a_carry_gets_only_what_the_take_can_spare():
    whole = card(1, 4, sound={"pre_lap": "x", "carries_over": "the room"})
    clip = plan_cuts([whole], editorial=True)[0]
    assert (clip.lead_s, clip.tail_s) == (0.0, 0.0)
    trimmed = card(1, 8, use_s=4.0, sound={"carries_over": "the room"})
    assert plan_cuts([trimmed], editorial=True)[0].tail_s == CARRY_S


def test_the_timeline_puts_each_picture_after_the_kept_part_of_the_one_before():
    cards = [card(1, 4, use_s=2.0), card(2, 6), card(3, 4, use_s=2.5, in_s=1.0)]
    assert [c.start_s for c in plan_cuts(cards, editorial=True)] == [0.0, 2.0, 8.0]
