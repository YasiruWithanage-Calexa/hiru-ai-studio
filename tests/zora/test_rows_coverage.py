"""The shot contract, the kernel, the checks and the risk rule on the rows (plan/2026-11-13 phases 1-2; the lab's
`lab/zora_rows/tests/test_lab.py`, ported). No model."""
from __future__ import annotations

import pytest

from contracts.coverage import checks, risk
from contracts.coverage.ledger import changes, plain
from contracts.coverage.scene import Coverage
from contracts.producer import PersonEdits
from hiru_ai.steps.coverage_kernel.logic import Kernel
from tests.zora.rows_world import data, scene

# The fixture was planned before the action budget (plan/2026-11-18c): its key handover (Nimal lifts
# the key from the box and places it in Dinu's palm, in S14 and S15) is two hard actions in one clip: real H-16 faults.
PRE_BUDGET = {"action_budget:h14", "action_budget:h15"}


@pytest.fixture(autouse=True)
def _recorded_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixture's takes were chosen on the clock before plan/2026-11-20 (`tests.clock_before`): on the measured one
    its S05 is 0.6 s short for L2, which the checks now report (and repair: a model made it)."""
    from tests.clock_before import clock_before_line_parts

    clock_before_line_parts(monkeypatch)


def found(cov: Coverage) -> list[checks.Finding]:
    """The findings, less the fixture's known pre-budget faults."""
    return [f for f in checks.find(cov) if f.key not in PRE_BUDGET]


def test_the_scene_loads_as_coverage_with_each_line_performed_once_and_no_findings() -> None:
    cov = scene()
    assert len(cov.clips) == 20
    assert {ln.lid: cov.code(ln.by) for ln in cov.lines.values()} == {"L2": "S05", "L3": "S08", "L4": "S11"}
    assert found(cov) == []
    assert [f.key for f in checks.find(cov)] == sorted(PRE_BUDGET)


def test_removing_a_line_clip_moves_the_line_to_a_clip_that_shows_the_speaker() -> None:
    cov = scene()
    res = Kernel(cov).apply([{"op": "remove", "shot": "S08"}], by="conductor")
    assert res.applied and "moves to the single" in res.notes[0]
    new = cov.clip(cov.lines["L3"].by)
    assert new is not None and new.slate == "3C-3" and new.sound_mode == "dialogue"
    assert found(cov) == []


def test_a_must_removal_is_risky_and_a_size_change_is_not() -> None:
    before = scene()
    after = before.copy()
    res = Kernel(after).apply([{"op": "remove", "shot": "S08"}], by="conductor")
    assert "removes S08, a must clip" in risk.reasons(res.applied, before, after, [])
    after2 = before.copy()
    res2 = Kernel(after2).apply([{"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}], by="conductor")
    assert risk.reasons(res2.applied, before, after2, []) == []


def test_a_model_cannot_write_what_a_person_locked_but_the_persons_words_can() -> None:
    cov = scene()
    k = Kernel(cov)
    k.apply([{"op": "retime", "shot": "S01", "take_s": 6}], by="conductor")
    assert "take_s" in cov.clips[0].locks
    res = k.apply([{"op": "retime", "shot": "S01", "take_s": 8}], by="author")
    assert res.rejected and "locked" in res.rejected[0]["reason"]
    assert not k.apply([{"op": "retime", "shot": "S01", "take_s": 8}], by="person").rejected


def test_changing_a_locked_field_by_the_persons_words_asks_first() -> None:
    before = scene()
    Kernel(before).apply([{"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}], by="person")
    after = before.copy()
    res = Kernel(after).apply([{"op": "set", "shot": "S01", "field": "size", "value": "CU"}], by="conductor")
    assert "changes S01's size, which a person set" in risk.reasons(res.applied, before, after, [])


def test_numbers_are_read_at_the_start_of_the_batch() -> None:
    cov = scene()
    res = Kernel(cov).apply([{"op": "remove", "shot": "S02"},
                             {"op": "set", "shot": "S04", "field": "size", "value": "CU"}], by="conductor")
    assert not res.rejected
    assert next(c for c in cov.clips if c.slate == "3C-1").size == "CU"  # the S04 of before the removal


def test_removals_land_all_or_none() -> None:
    cov = scene()
    res = Kernel(cov).apply([{"op": "remove", "shot": "S02"}, {"op": "remove", "shot": "S99"}], by="conductor")
    assert len(res.rejected) == 2 and len(cov.clips) == 20


def test_a_split_inside_one_block_is_refused_with_the_way_out() -> None:
    res = Kernel(scene()).apply([{"op": "split", "shot": "S05", "at_block": 2}], by="author")
    assert res.rejected and "insert a clip" in res.rejected[0]["reason"]


def test_an_insert_needs_its_picture_and_the_check_says_so() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "size": "INSERT", "take_s": 4, "first_block": 5,
                        "last_block": 5, "who": ["Dinu"]}], by="conductor")
    assert [f.code for f in found(cov)] == ["picture_empty"]


def test_a_model_made_overrun_is_repaired_and_a_person_set_one_is_reported() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "retime", "shot": "S11", "take_s": 4}], by="author")
    assert [f.fix for f in checks.find(cov) if f.code == "overrun"] == ["repair"]
    cov2 = scene()
    Kernel(cov2).apply([{"op": "retime", "shot": "S11", "take_s": 4}], by="conductor")
    assert [f.fix for f in checks.find(cov2) if f.code == "overrun"] == ["report"]


def test_a_persons_insert_keeps_their_size_and_words_and_a_priority_in_the_role_moves() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "role": "must", "size": "INSERT", "take_s": 4,
                        "first_block": 5, "last_block": 5, "what": "the key in Dinu's palm"}], by="conductor")
    c = cov.clips[15]
    assert (c.role, c.priority, c.locks) == ("insert", "must", {"size", "sees"})
    assert Kernel(cov).apply([{"op": "set", "shot": "S16", "field": "size", "value": "MS"}], by="author").rejected


def test_an_insert_with_no_size_is_an_insert_and_the_default_is_not_locked() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "role": "insert", "take_s": 4, "first_block": 5,
                        "last_block": 5, "what": "the key in Dinu's palm"}], by="conductor")
    assert (cov.clips[15].size, cov.clips[15].locks) == ("INSERT", {"sees"})


def test_no_operation_writes_a_lines_words() -> None:
    cov = scene()
    words = {lid: ln.text for lid, ln in cov.lines.items()}
    Kernel(cov).apply([{"op": "set", "shot": "S05", "field": "why", "value": "x"},
                       {"op": "line", "line": "L2", "to_shot": "S04"}], by="author")
    assert {lid: ln.text for lid, ln in cov.lines.items()} == words


def test_the_fingerprint_follows_the_rows_not_the_order_of_reading() -> None:
    assert scene().fingerprint() == scene().fingerprint()
    cov = scene()
    Kernel(cov).apply([{"op": "retime", "shot": "S01", "take_s": 8}], by="person")
    assert cov.fingerprint() != scene().fingerprint()


def test_the_ledger_reads_a_change_as_a_person_says_it() -> None:
    before = scene()
    after = before.copy()
    Kernel(after).apply([{"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}], by="person")
    assert changes(before, after) == ["S01 · size: MS → WIDE"]
    assert plain("S01 · size: MS → WIDE") == "S01's size went from MS to WIDE"


def test_row_of_keeps_every_column_and_writes_the_locks_where_the_plan_says() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "set", "shot": "S01", "field": "size", "value": "WIDE"},
                       {"op": "retime", "shot": "S01", "take_s": 8}], by="person")
    c = cov.clips[0]
    row = cov.row_of(c, number=1, row_id=c.row_id)
    source = data()["shots"][0]
    assert set(source) <= set(row)
    assert (row["framing"], row["duration_s"], row["duration_locked"]) == ("WIDE", 8, True)
    assert PersonEdits.of(row).zora_locks == ["size"] and PersonEdits.of(row).dump()["zora_locks"] == ["size"]
    again = Coverage.from_rows(data()["scene"], [row], data()["lines"], data()["characters"])
    assert again.clips[0].locks == {"take_s", "size"}


# ── §3.7 a clip that performs a line but is stored silent ─────────────────────────────────────────────────────────


def _silent(shot: str = "S08") -> Coverage:
    d = data()
    cov = Coverage.from_rows(d["scene"], d["shots"], d["lines"], d["characters"])
    c = cov.at(shot)
    assert c is not None
    c.sound_mode = "silent"
    return cov


def test_a_clip_that_performs_a_line_but_is_stored_silent_is_found_with_the_mode_it_needs() -> None:
    cov = _silent()
    (found,) = [f for f in checks.find(cov) if f.code == "line_unvoiced"]
    assert found.fix == "code" and "S08 performs L3" in found.sentence and "dialogue" in found.sentence
    ((clip, mode),) = checks.unvoiced(cov)
    assert (cov.code(clip.h), mode) == ("S08", "dialogue")


def test_a_line_heard_and_not_seen_is_voiced_off_screen() -> None:
    cov = _silent()
    c = cov.at("S08")
    assert c is not None
    c.on_screen = []
    assert checks.unvoiced(cov)[0][1] == "voiceover"


def test_the_sound_mode_op_fixes_it_and_refuses_to_silence_a_performing_clip() -> None:
    cov = _silent()
    k = Kernel(cov)
    assert not k.apply([{"op": "sound_mode", "shot": "S08", "value": "dialogue"}], by="code").rejected
    assert not [f for f in checks.find(cov) if f.code == "line_unvoiced"]
    res = k.apply([{"op": "sound_mode", "shot": "S08", "value": "silent"}], by="person")
    assert res.rejected and "must voice it" in res.rejected[0]["reason"]
    row = cov.row_of(cov.clips[7], number=8, row_id=cov.clips[7].row_id)
    assert (row["sound_mode"], row["word_target"]) == ("dialogue", 13)


def test_a_moved_line_is_voiced_by_sight_and_the_clip_it_left_goes_quiet() -> None:
    cov = scene()
    target = next(c for c in cov.clips if 3 in c.blocks and "Dinu" not in c.on_screen and c.h != cov.lines["L3"].by)
    n = cov.number_of(target.h)
    res = Kernel(cov).apply([{"op": "line", "line": "L3", "to_shot": f"S{n:02d}"}], by="person")
    assert not res.rejected and "voiced off screen" in res.applied[0]["text"]
    assert target.sound_mode == "voiceover"
    assert cov.at("S08") is not None and cov.at("S08").sound_mode == "ambient"  # type: ignore[union-attr]


# ── the action budget on an edit (plan/2026-11-18c phase 6) ───────────────────────────────────────────────────────


def _beats(cov: Coverage, code: str, *actions: str) -> None:
    clip = cov.at(int(code[1:]))
    assert clip is not None
    clip.ir = {**clip.ir, "beats": [{"start_s": 0, "end_s": 4, "action": a} for a in actions]}


def test_an_edit_that_puts_a_car_exit_in_one_clip_is_over_the_budget_and_repaired() -> None:
    before = scene()
    after = before.copy()
    _beats(after, "S03", "The car stops; Anudi opens the rear door, steps out and walks off toward the stall.")
    (f,) = [f for f in checks.new(before, after) if f.code == "action_budget"]
    assert f.fix == "repair" and f.sentence.startswith("S03 is over the action budget")
    assert "open the next clip on the result" in f.sentence


def test_a_door_opened_and_never_closed_is_found_once_and_closing_it_clears_it() -> None:
    before = scene()
    after = before.copy()
    _beats(after, "S03", "Anudi opens the rear door.")
    assert [f.code for f in checks.new(before, after) if f.code == "door_open"] == ["door_open"]
    _beats(after, "S04", "Anudi closes the rear door.")
    assert not [f for f in checks.new(before, after) if f.code == "door_open"]


def test_a_clip_that_speaks_and_opens_turned_away_is_found() -> None:
    before = scene()
    after = before.copy()
    _beats(after, "S05", "Initially facing into the vehicle, he turns and speaks.")
    assert [f.code for f in checks.new(before, after) if f.code == "speaker_hidden"] == ["speaker_hidden"]


def test_within_budget_is_not_a_finding() -> None:
    before = scene()
    after = before.copy()
    _beats(after, "S03", "Anudi, already out of the car with the door shut, nods and walks off.")
    assert not [f for f in checks.new(before, after) if f.code in ("action_budget", "door_open")]
