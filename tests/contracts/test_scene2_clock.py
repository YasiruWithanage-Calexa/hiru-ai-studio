"""Episode 1, Scene 2 through the picture clock (plan/2026-11-01b Phase 1)."""
from __future__ import annotations

from contracts.shotplan import ProposedShot, fit
from tests.services import scene2_fixture as scene2

OPENING = ProposedShot(0, 9, "MS", "Kasun and Anudi at the stall")  # the kernel splits it; not under test


def test_s05_and_s06_as_stored_are_crowded_and_nothing_is_trimmed():
    plan = [OPENING, ProposedShot(9, 13, "MCU", "Anudi takes the call", "voiceover", 8, True),
            ProposedShot(13, 19, "MCU", "Her smile disappears", None, 4, True)]
    r = fit(scene2.items(), plan, envelope_s=35)
    s05, s06 = r.shots[-2], r.shots[-1]
    assert r.crowded == [s05.number, s06.number]
    assert round(s05.need_s, 1) == 9.4 and s05.duration_s == 8 and s06.duration_s == 4
    assert any(f"S{s05.number:02d} needs about 9.4 s" in i.message for i in r.issues if i.code == "crowded")
    assert [ln.words for ln in r.lines if ln.line_id in ("l5", "l6")] == [13, 4]  # the lines are whole


def test_as_a_proposal_the_call_is_split_and_the_voice_follows_the_ring():
    plan = [OPENING, ProposedShot(9, 13, "MCU", "Anudi takes the call", "voiceover"),
            ProposedShot(13, 19, "MCU", "Her smile disappears")]
    r = fit(scene2.items(), plan, envelope_s=60)
    by_start = {s.start: s for s in r.shots}
    assert (by_start[9].end, by_start[12].start) == (12, 12), "the ring and the look first, then the voice"
    assert by_start[12].end == 13 and by_start[12].sound_mode.value == "voiceover"
    father = next(ln for ln in r.lines if ln.line_id == "l5")
    assert father.shot_number == by_start[12].number and father.overrun_s == 0
    assert not r.crowded and all(i.code != "line_overrun" for i in r.issues)


def test_the_voice_never_starts_before_the_phone_has_rung():
    locked = fit(scene2.items()[9:13], [ProposedShot(0, 4, duration=8, duration_locked=True)], envelope_s=60)
    assert locked.lines[0].start_s == 3.0 and locked.lines[0].beat_index == 1  # not 0.5 s into beat 0
