"""The checks (plan/2026-11-08e phase 2): the gold bins pass, and each mutant fails with the right sentence."""

from __future__ import annotations

import copy

import pytest

from contracts.raphael import checks
from contracts.raphael.bin import Bin
from contracts.raphael.wire import LENGTH_CAPS, ClipW, ReviewRow
from tests.raphael import gold


def keys(found: list[checks.Fault]) -> set[str]:
    return {f.key for f in checks.blocking(found)}


def one(found: list[checks.Fault], code: str) -> checks.Fault:
    return next(f for f in checks.blocking(found) if f.code == code)


def stage2(work: Bin, cap: float = 2) -> list[checks.Fault]:
    return checks.check_stage2(gold.brief(), work, cap=cap)


def grow(work: Bin, moment: int, take_s: int = 4) -> None:
    """Add a cinematic clip, a copy of the first, in `moment`."""
    clone = copy.deepcopy(work.extras()[0])
    clone.id, clone.take_s, clone.moment = f"c{work.next_no:02d}", take_s, moment
    work.next_no += 1
    work.clips.append(clone)
    work.reslate()


# ── the gold bins ────────────────────────────────────────────────────────────────────────────────


def test_run_3_passes_every_stage_1_check() -> None:
    assert checks.blocking(checks.check_stage1(gold.brief(), gold.stage1())) == []


def test_pass_5_passes_every_stage_2_check_at_the_default_cap() -> None:
    assert checks.blocking(stage2(gold.final())) == []


def test_pass_5_review_and_blend_notes_match_its_bin() -> None:
    work = gold.final()
    notes, review = gold.stage2_result()
    assert checks.review_faults(work, review) == []
    assert checks.missing_blend_notes(work, notes) == []


def test_a_phone_close_up_is_not_a_screen_text_report() -> None:
    work = gold.final()
    work.extras()[0].why = "A close-up of the phone: the message reads Dad on its screen."
    assert not [f for f in checks.check_stage2(gold.brief(), work) if "screen text" in f.sentence]


# ── stage 2 mutants ──────────────────────────────────────────────────────────────────────────────


def test_a_cinematic_clip_marked_must_fails() -> None:
    work = gold.final()
    work.extras()[0].priority = "must"
    assert any("marked must" in f.sentence for f in checks.blocking(stage2(work)))


def test_a_cinematic_clip_with_no_anchor_or_an_unknown_one_fails() -> None:
    work = gold.final()
    work.extras()[0].anchor = []
    work.extras()[1].anchor = ["c99"]
    found = checks.blocking(stage2(work))
    assert any("names no anchor" in f.sentence for f in found)
    assert any("c99 is not a must clip" in f.sentence for f in found)


def test_an_anchor_that_is_another_cinematic_clip_fails() -> None:
    work = gold.final()
    a, b = work.extras()[:2]
    a.anchor = [b.id]
    assert any(f"anchor {b.id} is not a must clip" in f.sentence for f in checks.blocking(stage2(work)))


def test_an_anchor_in_another_moment_fails_unless_it_is_a_transition_to_a_neighbour() -> None:
    work = gold.final()
    e = work.extras()[0]
    far = next(c for c in work.musts() if abs(c.moment - e.moment) > 1)
    e.anchor = [far.id]
    assert any("an anchor is in" in f.sentence for f in checks.blocking(stage2(work)))
    near = next(c for c in work.musts() if abs(c.moment - e.moment) == 1)
    e.anchor, e.blend = [near.id], "transition"
    assert not any("an anchor is in" in f.sentence for f in checks.blocking(stage2(work)))


def test_the_same_angle_as_the_anchor_fails() -> None:
    work = gold.final()
    e = work.extras()[0]
    anchor = work.by_id(e.anchor[0])
    assert anchor is not None
    e.role, e.technique = anchor.role, anchor.technique
    assert any("that is an alternate" in f.sentence for f in checks.blocking(stage2(work)))


def test_a_speaking_cinematic_clip_fails() -> None:
    work = gold.final()
    work.extras()[0].speaks = True
    assert any("cinematic clip is silent" in f.sentence for f in checks.blocking(stage2(work)))


def test_four_cinematic_clips_in_a_moment_fail_and_three_pass() -> None:
    work = gold.final()
    moment = work.extras()[0].moment
    while sum(1 for c in work.extras() if c.moment == moment) < 3:
        grow(work, moment)
    assert f"cinematic:crowded:{moment}" not in keys(stage2(work, cap=3))
    grow(work, moment)
    assert f"cinematic:crowded:{moment}" in keys(stage2(work, cap=3))


@pytest.mark.parametrize("cap", LENGTH_CAPS)
def test_the_bin_over_each_cap_fails_and_at_the_cap_passes(cap: float) -> None:
    work = gold.final()  # 112 s of takes in a 60 s scene
    if cap == 1.5:
        assert "length:stage2" in keys(stage2(work, cap))  # 90 s: already over
        return
    assert "length:stage2" not in keys(stage2(work, cap))
    room, n = 60 * cap - work.counts()["take_s"], 0
    while room >= 4:  # fill to exactly the cap, one moment each so no moment is crowded
        grow(work, 100 + n)
        room -= 4
        n += 1
    assert work.counts()["take_s"] <= 60 * cap
    assert "length:stage2" not in keys(stage2(work, cap))
    grow(work, 200, take_s=8)
    assert "length:stage2" in keys(stage2(work, cap))


def test_stage_1_keeps_its_own_cap_of_one_and_a_half() -> None:
    assert "length:over" in keys(checks.check_stage1(gold.brief(), gold.final()))  # 112 s > 90 s
    assert "length:over" not in keys(checks.check_stage1(gold.brief(), gold.stage1()))  # 70 s


def test_a_heard_voice_in_frame_fails_in_any_clip() -> None:
    work = gold.final()
    e = work.extras()[0]
    assert e.ir is not None
    e.ir = {**e.ir, "subjects": [{"id": "C03", "description": "Father stands under the awning", "action": "waits"}]}
    found = checks.blocking(stage2(work))
    assert any("only heard" in f.sentence and e.id in f.clips for f in found)


def test_a_beat_that_says_someone_speaks_in_a_silent_clip_fails() -> None:
    work = gold.final()
    e = work.extras()[0]
    assert e.ir is not None
    e.ir = {**e.ir, "beats": [{"action": "Anudi says thank you softly"}]}
    assert any("does not perform a line" in f.sentence for f in checks.blocking(stage2(work)))


def test_a_clip_with_no_design_fails() -> None:
    work = gold.final()
    work.extras()[0].ir = None
    assert any("has no design yet" in f.sentence for f in checks.blocking(stage2(work)))


def test_a_refused_technique_in_a_clip_text_fails() -> None:
    work = gold.final()
    work.extras()[0].editor_note = "Do a dolly zoom here"
    assert any("a dolly zoom" in f.sentence for f in checks.blocking(stage2(work)))


# ── the review ───────────────────────────────────────────────────────────────────────────────────


def test_the_review_must_cover_every_moment_once_and_match_the_bin() -> None:
    work = gold.final()
    _, review = gold.stage2_result()
    assert checks.review_faults(work, review[:-1])  # one moment missing
    assert any("reviewed 2 times" in w for w in checks.review_faults(work, [*review, review[0]]))
    flipped = [
        ReviewRow(moment=r.moment, earns=not r.earns, why=r.why) if r.moment == review[0].moment else r for r in review
    ]
    assert any("says earns" in w for w in checks.review_faults(work, flipped))
    blank = [ReviewRow(moment=review[0].moment, earns=review[0].earns, why=" "), *review[1:]]
    assert any("has no reason" in w for w in checks.review_faults(work, blank))
    extra = [*review, ReviewRow(moment=99, earns=False, why="x")]
    assert any("not in the intended cut" in w for w in checks.review_faults(work, extra))


def test_a_review_of_noes_is_right_for_a_bin_with_no_cinematic_clips() -> None:
    work = gold.stage1()
    assert work.edit is not None
    review = [ReviewRow(moment=m.n, earns=False, why="the must clip carries it") for m in work.edit.moments]
    assert checks.review_faults(work, review) == []


def test_a_blend_note_must_name_each_cinematic_clip() -> None:
    work = gold.final()
    notes, _ = gold.stage2_result()
    gone = work.extras()[0].id
    assert checks.missing_blend_notes(work, [n for n in notes if not n.startswith(gone)]) == [gone]


# ── stage 1 mutants (DaVinci's checks, ported) ───────────────────────────────────────────────────


def test_a_block_with_no_must_clip_fails() -> None:
    work = gold.stage1()
    work.clips = [c for c in work.clips if 3 not in c.blocks]
    assert any(f.key == "coverage:must:3" for f in checks.blocking(checks.check_stage1(gold.brief(), work)))


def test_a_line_no_must_clip_performs_fails() -> None:
    work = gold.stage1()
    for c in work.clips:
        c.speaks = False
    assert any(
        f.code == "coverage" and "performed by no must clip" in f.sentence
        for f in checks.blocking(checks.check_stage1(gold.brief(), work))
    )


def test_an_overrun_is_reported_and_never_blocks() -> None:
    work = gold.stage1()
    speaking = next(c for c in work.clips if c.lines and c.take_s == 4)
    speaking.blocks = [b.index for b in gold.scene().blocks]
    speaking.lines = [b.line_id for b in gold.scene().lines if b.line_id]
    found = checks.check_stage1(gold.brief(), work)
    assert any(f.key.startswith("clock:overrun") and f.fix == "report" for f in found)
    assert not any(f.key.startswith("clock:overrun") for f in checks.blocking(found))


def test_a_missing_edit_plan_blocks() -> None:
    work = gold.stage1()
    work.edit = None
    assert "edit:none" in keys(checks.check_stage1(gold.brief(), work))


def test_inconsistent_wording_in_one_moment_fails_and_names_the_odd_clip() -> None:
    work = gold.stage1()
    by_moment: dict[int, list] = {}
    for c in work.clips:
        if c.role not in ("establishing", "atmosphere"):
            by_moment.setdefault(c.moment, []).append(c)
    group = next(g for g in by_moment.values() if len(g) >= 2)
    assert group[1].ir is not None
    group[1].ir = {**group[1].ir, "lighting": "Bright studio light, nothing like the rain"}
    found = one(checks.check_stage1(gold.brief(), work), "consistency")
    assert group[1].id in found.clips


def test_a_clip_menu_round_trips_through_clip_w() -> None:
    clip = gold.stage1().clips[0]
    row = {k: v for k, v in clip.model_dump().items() if k not in ("slate", "stage", "anchor", "blend")}
    assert ClipW.model_validate(row).menu().take_s == clip.take_s


# ── plan/2026-11-12: a heard line's device is shown (house rule H-12), report only ────────────────────────────────────


def _device_scene():
    scene = gold.scene().model_copy(deep=True)
    line = next(b for b in scene.blocks if b.line_id)
    line.device = "phone"
    return scene, line


def test_a_line_heard_through_a_device_no_clip_shows_is_reported_never_blocking():
    scene, line = _device_scene()
    work = copy.deepcopy(gold.stage1())
    for c in work.clips:
        c.summary, c.ir = "Dinu drives on.", None
    found = checks.device_unseen(scene, work)
    assert [f.key for f in found] == [f"device:{line.line_id}"] and checks.blocking(found) == []
    assert "house rule H-12" in found[0].sentence


def test_a_clip_on_the_line_or_just_before_it_that_shows_the_device_answers_it():
    scene, line = _device_scene()
    work = copy.deepcopy(gold.stage1())
    for c in work.clips:
        c.summary, c.ir = "Dinu drives on.", None
    work.clips[0].blocks = [line.index - 1] if line.index else [line.index]
    work.clips[0].summary = "The phone in its dashboard mount lights up with Aruni's name."
    assert checks.device_unseen(scene, work) == []
    work.clips[0].blocks = [line.index + 3]  # the phone shown, but nowhere near the line
    assert len(checks.device_unseen(scene, work)) == 1


def test_a_scene_with_no_device_line_gets_no_device_report():
    assert checks.device_unseen(gold.scene(), gold.stage1()) == []
