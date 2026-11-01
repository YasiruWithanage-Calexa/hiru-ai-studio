"""The shot-plan kernel: every rule it promises, one test each."""
from __future__ import annotations

from contracts.shotplan import (
    LEAD_IN_S,
    LINE_GAP_S,
    TAIL_S,
    Item,
    ProposedShot,
    fit,
    needed_seconds,
    normalise,
    shot_clock,
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
    assert first.shot_number == 1 and first.start_s == 1.5  # after the action's picture time, not the lead-in
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


def test_a_voice_that_is_heard_not_seen_is_voiceover():
    for mark in ("on the phone", "over the phone", "off screen", "off-screen", "O.S."):
        assert sound_mode_for([line(0, 3, delivery=mark)], None) is SoundMode.VOICEOVER, mark
    # one on-camera line in the shot keeps it a dialogue shot
    assert sound_mode_for([line(0, 3, delivery="on the phone"), line(1, 3, "KAMALA", sid="c2")],
                          None) is SoundMode.DIALOGUE
    assert sound_mode_for([line(0, 3, delivery="softly")], None) is SoundMode.DIALOGUE


def test_two_speakers_in_a_dialogue_shot_are_reported():
    items = [line(0, 4), line(1, 4, "KAMALA", sid="c2")]
    r = fit(items, [ProposedShot(0, 2)], envelope_s=60)
    assert [(i.code, i.shot_number) for i in r.issues if i.code == "multi_speaker"] == [("multi_speaker", 1)]
    assert r.shots[0].speaker_id is None and r.shots[0].line_ids == ["l0", "l1"]  # nothing dropped or trimmed
    apart = fit(items, [ProposedShot(0, 1), ProposedShot(1, 2)], envelope_s=60)
    assert not [i for i in apart.issues if i.code == "multi_speaker"]


def test_one_speaker_and_unlinked_speakers_are_counted_by_name():
    same = fit([line(0, 4), line(1, 4)], [ProposedShot(0, 2)], envelope_s=60)
    assert not [i for i in same.issues if i.code == "multi_speaker"]
    unlinked = fit([line(0, 4, "NIMAL", sid=None), line(1, 4, "KAMALA", sid=None)], [ProposedShot(0, 2)],
                   envelope_s=60)
    assert [i.code for i in unlinked.issues if i.code == "multi_speaker"] == ["multi_speaker"]


def test_two_voices_in_a_voiceover_shot_are_not_a_lip_sync_risk():
    items = [line(0, 4, delivery="V.O."), line(1, 4, "KAMALA", delivery="V.O.", sid="c2")]
    r = fit(items, [ProposedShot(0, 2)], envelope_s=60)
    assert r.shots[0].sound_mode is SoundMode.VOICEOVER
    assert not [i for i in r.issues if i.code == "multi_speaker"]


def test_silent_seconds_and_share():
    items = [action(0, 40), line(1, 4), action(2, 3)]  # 8 s silent · 4 s spoken · 4 s silent
    r = fit(items, [ProposedShot(0, 1), ProposedShot(1, 2), ProposedShot(2, 3)], envelope_s=60)
    assert (r.silent_s, r.total_s) == (12, 16) and r.silent_share == 0.75
    empty = fit([], [], envelope_s=60)
    assert empty.silent_s == 0 and empty.silent_share == 0.0


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


# ── the picture clock (plan/2026-11-01b Phase 1) ───────────────────────────────────────────────


def pic(i: int, screen: str = "act", events: int = 1, implied: bool = False) -> Item:
    return Item(i, "action", f"picture {i}", screen=screen, events=events, implied=implied)


def test_a_shot_of_one_line_and_no_action_times_exactly_as_before():
    one = line(0, 9)
    assert needed_seconds([one]) == LEAD_IN_S + 9 / 2.2 + TAIL_S
    two = [line(0, 4), line(1, 4, "KAMALA", sid="c2")]
    assert needed_seconds(two) == LEAD_IN_S + 2 * (4 / 2.2) + LINE_GAP_S + TAIL_S


def test_a_line_starts_after_the_pictures_before_it():
    slots, need = shot_clock([pic(0), pic(1), pic(2, "info"), line(3, 13)])
    spoken = next(s for s in slots if s.is_line)
    assert spoken.start_s == 3.0  # two 1.5 s actions; information takes no time of its own
    assert round(need, 1) == 9.4  # 3.0 + 13 words at 2.2/s + the tail


def test_an_action_before_the_first_line_replaces_the_lead_in():
    assert shot_clock([pic(0, "with_line"), line(1, 4)])[0][1].start_s == LEAD_IN_S
    assert shot_clock([pic(0, "info"), line(1, 4)])[0][0].start_s == LEAD_IN_S


def test_an_action_after_the_last_line_has_no_tail_and_a_move_takes_longer():
    _, need = shot_clock([line(0, 4), pic(1, "move")])
    assert round(need, 2) == round(LEAD_IN_S + 4 / 2.2 + 2.5, 2)
    assert shot_clock([pic(0, "move")])[1] == 2.5
    assert shot_clock([pic(0, "act", events=2)])[1] == 3.0  # each visible event takes its own time
    assert shot_clock([pic(0, "unheard-of")])[1] == 1.5  # unknown counts as `act`


def test_a_voice_after_the_ring_lands_after_it():
    items = [pic(0), pic(1), pic(2, "info"), line(3, 13, "FATHER", "on the phone")]
    r = fit(items, [ProposedShot(0, 4, duration=8, duration_locked=True)], envelope_s=60)
    assert r.lines[0].start_s == 3.0 and r.lines[0].beat_index == 1  # beat 3-6 s, not beat 0
    assert r.lines[0].overrun_s > 0  # 3.0 + 5.9 runs past an 8 s cut: reported, not trimmed


def test_a_locked_shot_that_holds_more_than_it_can_show_is_crowded():
    items = [pic(0), pic(1), pic(2, "info"), pic(3, implied=True), line(4, 13, "FATHER", "on the phone")]
    r = fit(items, [ProposedShot(0, 5, duration=8, duration_locked=True)], envelope_s=60)
    crowded = [i for i in r.issues if i.code == "crowded"]
    assert [(i.shot_number, i.message) for i in crowded] == [
        (1, "S01 needs about 10.9 s to show what it holds; it is 8 s.")]
    assert r.crowded == [1] and r.shots[0].duration_s == 8 and round(r.shots[0].need_s, 1) == 10.9
    assert r.shots[0].picture_s == 4.5 and r.need_s == 11
    assert [ln.words for ln in r.lines] == [13]  # nothing was trimmed


def test_a_fixed_length_production_reports_crowded_too():
    r = fit([pic(0, "act", events=3)], [ProposedShot(0, 1)], envelope_s=60, fixed_seconds=4)  # 4.5 s in one block
    assert r.shots[0].duration_s == 4 and r.crowded == [1]
    split = fit([pic(0), pic(1), pic(2)], [ProposedShot(0, 3)], envelope_s=60, fixed_seconds=4)
    assert len(split.shots) == 2 and not split.crowded  # a fixed length splits what it can; it does not squeeze


def test_an_unlocked_shot_is_split_at_a_block_boundary_not_squeezed():
    items = [pic(0), pic(1), pic(2, "info"), line(3, 13, "FATHER", "on the phone")]
    r = fit(items, [ProposedShot(0, 4, title="Anudi takes the call")], envelope_s=60)
    assert [(s.start, s.end) for s in r.shots] == [(0, 3), (3, 4)]
    assert not r.crowded and not [i for i in r.issues if i.code == "line_overrun"]
    assert r.shots[1].camera_link is CameraLink.CONTINUOUS  # the cut falls between a picture and a line
    assert r.shots[1].title == "Anudi takes the call (2)"
    assert r.lines[0].shot_number == 2 and r.lines[0].start_s == r.shots[1].start_s + LEAD_IN_S


def test_a_split_that_starts_on_an_action_is_a_cut():
    items = [line(0, 12), pic(1), pic(2), line(3, 12)]
    r = fit(items, [ProposedShot(0, 4)], envelope_s=60)
    assert [(s.start, s.end) for s in r.shots] == [(0, 3), (3, 4)] or len(r.shots) > 1
    follow = [s for s in r.shots if s.start in (1, 2)]
    assert follow and all(s.camera_link is CameraLink.CUT for s in follow)


def test_an_action_that_plays_under_the_next_line_stays_with_it():
    items = [pic(0, "move"), pic(1, "move"), pic(2, "move"), pic(3, "with_line"), line(4, 12)]
    r = fit(items, [ProposedShot(0, 5)], envelope_s=60)
    assert len(r.shots) == 2 and (r.shots[1].start, r.shots[1].end) == (3, 5)


def test_lines_are_never_split_inside_and_a_long_line_is_still_reported():
    items = [pic(0), line(1, 30)]
    r = fit(items, [ProposedShot(0, 2)], envelope_s=60)
    assert [ln.words for ln in r.lines] == [30]
    assert {"long_line", "line_overrun"} <= {i.code for i in r.issues}


def test_the_envelope_issue_says_what_the_scene_needs():
    items = [pic(i, "move") for i in range(8)]  # 20 s of pictures
    r = fit(items, [ProposedShot(0, 8)], envelope_s=12)
    assert r.need_s >= r.total_s and r.over_envelope_s == r.need_s - 12
    env = next(i for i in r.issues if i.code == "envelope")
    assert env.message == f"The scene needs {r.need_s} s on screen; its envelope is 12 s ({r.over_envelope_s} s over)."


def test_one_block_that_shows_more_than_the_longest_shot_is_reported_not_hidden():
    r = fit([pic(0, "move", events=4)], [ProposedShot(0, 1)], envelope_s=60)  # 10 s of running, cannot be cut
    assert r.shots[0].duration_s == 8 and r.crowded == [1]
    assert any(i.code == "crowded" and "needs about 10.0 s" in i.message for i in r.issues)


def test_a_line_that_is_too_long_is_reported_once_as_a_line_not_as_crowded():
    r = fit([line(0, 30)], [ProposedShot(0, 1)], envelope_s=60)
    assert "long_line" in {i.code for i in r.issues} and r.crowded == []
