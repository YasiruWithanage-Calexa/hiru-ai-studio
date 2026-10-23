"""Timing rules. The first block mirrors the frontend's `src/lib/veo/timing.test.ts` case for
case, so the Director panel and the server can never disagree about where a line overruns."""
import itertools

import pytest

from contracts.timing import (
    default_beats,
    effective_word_target,
    exceeds_shot_word_target,
    is_slow_delivery,
    over_budget,
    overrun_seconds,
    shot_word_target,
    slot_word_budget,
    speech_seconds,
    word_target,
    words_in,
)
from contracts.veo import SoundMode, nearest_reachable_total, reachable_totals, snap_duration

# ── parity with timing.test.ts ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seconds", [4, 6, 8])
def test_snap_keeps_renderable_lengths(seconds):
    assert snap_duration(seconds) == seconds


@pytest.mark.parametrize(("given", "snapped"), [(2, 4), (4.9, 4), (7.2, 8), (15, 8)])
def test_snap_to_nearest(given, snapped):
    assert snap_duration(given) == snapped


@pytest.mark.parametrize(("given", "snapped"), [(5, 6), (7, 8)])
def test_snap_ties_go_longer(given, snapped):
    assert snap_duration(given) == snapped


def test_shot_word_target_matches_ladder():
    assert [shot_word_target(s) for s in (4, 6, 8)] == [8, 13, 17]
    assert shot_word_target(1) == 4


def test_speech_seconds_default_rate():
    assert f"{speech_seconds(4):.1f}" == "1.8"
    assert f"{speech_seconds(7):.1f}" == "3.2"


def test_slow_deliveries():
    assert is_slow_delivery("(trembling, quietly)")
    assert not is_slow_delivery("softly")
    assert speech_seconds(9, "whispered") == 5


def test_overrun_flag_threshold():
    assert not exceeds_shot_word_target(22, 8)
    assert exceeds_shot_word_target(24, 8)


@pytest.mark.parametrize("duration", [4, 6, 8])
def test_default_beats_cover_shot(duration):
    beats = default_beats(duration)
    assert beats[0][0] == 0
    assert beats[-1][1] == duration
    for prev, cur in itertools.pairwise(beats):
        assert cur[0] == prev[1]


def test_overrun_seconds():
    assert f"{overrun_seconds(start_sec=14, words=7, shot_end_sec=16):.1f}" == "1.2"
    assert overrun_seconds(start_sec=11, words=4, shot_end_sec=16) == 0


# ── server-only rules ─────────────────────────────────────────────────────────────────────


def test_default_beats_rejects_unrenderable():
    with pytest.raises(ValueError):
        default_beats(10)


def test_parentheticals_are_not_speech():
    assert words_in("(whispering, barely audible) come back home") == 3
    assert words_in(None) == 0


@pytest.mark.parametrize("mode", [SoundMode.AMBIENT, SoundMode.MUSIC_ONLY, SoundMode.SILENT])
def test_wordless_modes_have_no_target(mode):
    assert word_target(mode, 8) == 0
    assert effective_word_target(mode, 8, ["whisper"]) == 0


def test_slow_line_lowers_effective_target():
    assert effective_word_target(SoundMode.DIALOGUE, 8, ["calm"]) == 17
    assert effective_word_target(SoundMode.DIALOGUE, 8, ["", "halting"]) == 13


def test_slot_budget_has_no_floor_and_needs_real_excess():
    assert slot_word_budget(1) == 2
    assert not over_budget(3, 2, slot=True)  # under ×1.6
    assert not over_budget(2, 1, slot=True)  # over ×1.6 but only one word over
    assert over_budget(4, 2, slot=True)  # over ×1.6 and two words over
    assert not over_budget(5, 0)  # no target, no flag


def test_reachable_totals_are_even_on_ladder():
    assert all(t % 2 == 0 for t in reachable_totals(3))
    assert min(reachable_totals(3)) == 12 and max(reachable_totals(3)) == 24
    assert nearest_reachable_total(25, 3) == 24
    assert nearest_reachable_total(25, 4) == 24  # tie 24/26 → shorter
    assert nearest_reachable_total(10, 0) == 0
