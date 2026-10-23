"""The shot-plan kernel: every rule it promises, one test each."""
from __future__ import annotations

from contracts.shotplan import (
    LEAD_IN_S,
    Item,
    ProposedShot,
    fit,
    needed_seconds,
    normalise,
    sound_mode_for,
)
from contracts.veo import CameraLink, FrameStrategy, SoundMode


def line(i: int, words: int, speaker: str = "NIMAL", delivery: str = "", sid: str | None = "c1") -> Item:
    return Item(i, "dialogue", " ".join(["word"] * words), speaker, sid, delivery, f"l{i}")


def action(i: int, words: int = 5) -> Item:
    return Item(i, "action", " ".join(["act"] * words))


def test_shortest_rung_that_holds_the_speech():
    items = [line(0, 4)]  # 0.5 + 4/2.2 + 0.5 ≈ 2.8 s → 4 s
    r = fit(items, [ProposedShot(0, 1)], envelope_s=60)
    assert r.shots[0].duration_s == 4
    items = [line(0, 10)]  # ≈ 5.5 s → 6 s
    assert fit(items, [ProposedShot(0, 1)], envelope_s=60).shots[0].duration_s == 6


def test_planner_may_ask_for_longer_but_not_shorter():
    items = [line(0, 10)]
    assert fit(items, [ProposedShot(0, 1, duration=8)], envelope_s=60).shots[0].duration_s == 8
    assert fit(items, [ProposedShot(0, 1, duration=4)], envelope_s=60).shots[0].duration_s == 6


def test_fixed_length_production_forces_every_shot():
    items = [line(0, 3), action(1)]
    r = fit(items, [ProposedShot(0, 1), ProposedShot(1, 2)], envelope_s=60, fixed_seconds=8)
    assert [s.duration_s for s in r.shots] == [8, 8]


def test_lines_are_bound_in_order_with_scene_times_and_beats():
    items = [action(0), line(1, 4), line(2, 4, "KAMALA", sid="c2")]
    r = fit(items, [ProposedShot(0, 2), ProposedShot(2, 3)], envelope_s=60)
    assert [fl.line_id for fl in r.lines] == ["l1", "l2"]
    first, second = r.lines
    assert first.shot_number == 1 and first.start_s == LEAD_IN_S
    assert second.shot_number == 2 and second.start_s == r.shots[1].start_s + LEAD_IN_S
    assert first.beat_index == 0
    assert r.shots[0].speaker_id == "c1" and r.shots[1].speaker_id == "c2"


def test_a_shot_that_cannot_hold_its_lines_splits_into_a_continuous_follow_on():
    items = [line(0, 12), line(1, 12), line(2, 12)]  # each ≈ 5.5 s; two never fit 8 s
    r = fit(items, [ProposedShot(0, 3, title="Nimal pleads")], envelope_s=60)
    assert len(r.shots) == 3
    assert [s.camera_link for s in r.shots] == [CameraLink.CUT, CameraLink.CONTINUOUS, CameraLink.CONTINUOUS]
    assert r.shots[1].frame_strategy is FrameStrategy.CARRY_LAST_FRAME
    assert r.shots[1].title == "Nimal pleads (2)"
    assert not [i for i in r.issues if i.code == "line_overrun"]


def test_a_line_longer_than_any_shot_is_reported_never_trimmed():
    items = [line(0, 30)]  # ≈ 13.6 s
    r = fit(items, [ProposedShot(0, 1)], envelope_s=60)
    assert r.shots[0].duration_s == 8
    codes = {i.code for i in r.issues}
    assert {"line_overrun", "long_line"} <= codes
    assert r.lines[0].overrun_s > 0
    assert r.lines[0].words == 30  # nothing removed


def test_a_locked_length_is_kept_and_the_overrun_reported():
    items = [line(0, 12)]  # needs 6 s
    r = fit(items, [ProposedShot(0, 1, duration=4, duration_locked=True)], envelope_s=60)
    assert r.shots[0].duration_s == 4
    assert any(i.code == "line_overrun" for i in r.issues)


def test_envelope_overrun_is_reported_and_short_scenes_are_not_padded():
    items = [action(i, 40) for i in range(3)]
    over = fit(items, [ProposedShot(i, i + 1) for i in range(3)], envelope_s=16)
    assert over.total_s == 24 and over.over_envelope_s == 8
    assert any(i.code == "envelope" for i in over.issues)
    short = fit([action(0, 3)], [ProposedShot(0, 1)], envelope_s=60)
    assert short.total_s == 4


def test_gaps_and_overlaps_are_repaired_and_flagged():
    shots, repaired = normalise([ProposedShot(1, 3), ProposedShot(2, 5)], 6)
    assert [(s.start, s.end) for s in shots] == [(0, 3), (3, 6)]
    assert repaired
    shots, repaired = normalise([ProposedShot(0, 2), ProposedShot(2, 4)], 4)
    assert not repaired


def test_no_spoken_mode_without_words_and_no_silence_with_words():
    assert sound_mode_for([], SoundMode.DIALOGUE.value) is SoundMode.AMBIENT
    assert sound_mode_for([], SoundMode.SILENT.value) is SoundMode.SILENT
    assert sound_mode_for([line(0, 3)], SoundMode.SILENT.value) is SoundMode.DIALOGUE
    assert sound_mode_for([line(0, 3, delivery="V.O.")], None) is SoundMode.VOICEOVER
    assert sound_mode_for([line(0, 3, delivery="sings softly")], None) is SoundMode.SUNG


def test_slow_delivery_needs_more_time_and_lowers_the_word_target():
    assert needed_seconds([line(0, 9, delivery="whispering")]) > needed_seconds([line(0, 9)])
    r = fit([line(0, 9, delivery="trembling")], [ProposedShot(0, 1)], envelope_s=60)
    assert r.shots[0].word_target < 13


def test_word_budget_overrun_is_reported():
    items = [line(0, 15)]
    r = fit(items, [ProposedShot(0, 1, duration=4, duration_locked=True)], envelope_s=60)
    assert any(i.code == "word_budget" for i in r.issues)


def test_first_shot_cannot_continue_from_nothing():
    r = fit([action(0)], [ProposedShot(0, 1, camera_link=CameraLink.CONTINUOUS.value)], envelope_s=60)
    assert r.shots[0].camera_link is CameraLink.CUT
    assert r.shots[0].frame_strategy is FrameStrategy.GENERATE


def test_empty_scene():
    r = fit([], [], envelope_s=60)
    assert r.shots == [] and r.total_s == 0
