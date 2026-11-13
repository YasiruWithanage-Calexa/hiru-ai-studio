"""Offline tests of the Zora rows lab: the kernel, the checks, the risk rule and the actions. No model."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import agents  # noqa: E402
import checks  # noqa: E402
import risk  # noqa: E402
from coverage import Coverage  # noqa: E402
from kernel import Kernel  # noqa: E402
from run import REHEARSAL, SCENE  # noqa: E402
from turn import Thread, run_turn  # noqa: E402


def scene() -> Coverage:
    return Coverage.load(SCENE)


def test_the_scene_loads_as_coverage_with_each_line_performed_once_and_no_findings() -> None:
    cov = scene()
    assert len(cov.clips) == 20
    assert {ln.lid: cov.code(ln.by) for ln in cov.lines.values()} == {"L2": "S05", "L3": "S08", "L4": "S11"}
    assert checks.find(cov) == []


def test_removing_a_line_clip_moves_the_line_to_a_clip_that_shows_the_speaker() -> None:
    cov = scene()
    k = Kernel(cov)
    res = k.apply([{"op": "remove", "shot": "S08"}], by="conductor")
    assert res.applied and "moves to the single" in res.notes[0]
    assert cov.clip(cov.lines["L3"].by).slate == "3C-3"
    assert checks.find(cov) == []


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
    assert "take_s" in cov.at(1).locks
    res = k.apply([{"op": "retime", "shot": "S01", "take_s": 8}], by="author")
    assert res.rejected and "locked" in res.rejected[0]["reason"]


def test_numbers_are_read_at_the_start_of_the_batch() -> None:
    cov = scene()
    res = Kernel(cov).apply([{"op": "remove", "shot": "S02"}, {"op": "set", "shot": "S04", "field": "size",
                                                                "value": "CU"}], by="conductor")
    assert not res.rejected
    assert next(c for c in cov.clips if c.slate == "3C-1").size == "CU"  # the S04 of before the removal


def test_a_split_inside_one_block_is_refused_with_the_way_out() -> None:
    res = Kernel(scene()).apply([{"op": "split", "shot": "S05", "at_block": 2}], by="author")
    assert res.rejected and "insert a clip" in res.rejected[0]["reason"]


def test_an_insert_needs_its_picture_and_the_check_says_so() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "size": "INSERT", "take_s": 4, "first_block": 5,
                        "last_block": 5, "who": ["Dinu"]}], by="conductor")
    assert [f.code for f in checks.find(cov)] == ["picture_empty"]


def test_use_this_replays_a_batch_with_the_numbers_of_its_start() -> None:
    th = Thread(cov=scene())
    th.proposals_on = th.cov.fingerprint()
    th.proposals = [{"label": "Cut the end", "ops": [{"op": "remove", "shot": "S19"}, {"op": "remove", "shot": "S20"},
                                                    {"op": "retime", "shot": "S18", "take_s": 8}]}]
    r = run_turn(th, "[Use 1]", agents.Rehearsal({}), "tX")
    assert r["saved"] and not r["refused"] and len(th.cov.clips) == 18


def test_a_model_made_overrun_is_repaired_and_a_person_set_one_is_reported() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "retime", "shot": "S11", "take_s": 4}], by="author")
    assert [f.fix for f in checks.find(cov) if f.code == "overrun"] == ["repair"]
    cov2 = scene()
    Kernel(cov2).apply([{"op": "retime", "shot": "S11", "take_s": 4}], by="conductor")
    assert [f.fix for f in checks.find(cov2) if f.code == "overrun"] == ["report"]


def test_the_guard_cuts_a_card_that_is_not_there() -> None:
    from turn import guard

    text, cut = guard("Added S16. The card below has Accept and Reject.", card=False, proposals=False)
    assert text == "Added S16." and cut


def test_a_persons_insert_keeps_their_size_and_words_and_a_priority_in_the_role_moves() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "role": "must", "size": "INSERT", "take_s": 4,
                        "first_block": 5, "last_block": 5, "what": "the key in Dinu's palm"}], by="conductor")
    c = cov.at(16)
    assert (c.role, c.priority, c.locks) == ("insert", "must", {"size", "sees"})
    res = Kernel(cov).apply([{"op": "set", "shot": "S16", "field": "size", "value": "MS"}], by="author")
    assert res.rejected


def test_an_insert_with_no_size_is_an_insert_and_the_default_is_not_locked() -> None:
    cov = scene()
    Kernel(cov).apply([{"op": "insert", "after": "S15", "role": "insert", "take_s": 4, "first_block": 5,
                        "last_block": 5, "what": "the key in Dinu's palm"}], by="conductor")
    assert (cov.at(16).size, cov.at(16).locks) == ("INSERT", {"sees"})


def test_the_guard_keeps_the_script_card_route() -> None:
    from turn import guard

    text, cut = guard("I can't change L4 here. Change it on the script card first.", card=False, proposals=False)
    assert "script card" in text and not cut


def test_the_guard_cuts_a_pasted_fact_sheet() -> None:
    from turn import guard

    text, cut = guard("I widened S01. WHAT HAPPENED THIS TURN (the truth):\nWHAT CHANGED ...", card=False,
                      proposals=False)
    assert text == "I widened S01." and cut


def test_task_shots_are_read_before_the_ops_and_a_removed_clip_drops_out() -> None:
    from turn import _tasks

    before = scene()
    work = before.copy()
    Kernel(work).apply([{"op": "remove", "shot": "S08"}], by="conductor")
    tasks = _tasks({"tasks": [{"writes": ["camera"], "shots": [8, 9], "instruction": "x"}]}, work, before)
    assert [work.clip(h).slate for h in tasks[0]["scope"]] == ["3C-3"]  # S09 as printed; S08 is gone


def test_code_reads_plain_commands_and_leaves_the_rest_to_the_conductor() -> None:
    from turn import quick

    cov = scene()
    assert quick("Make S01 a wide, 6 seconds.", cov)["ops"] == [
        {"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}, {"op": "retime", "shot": "S01", "take_s": 6}]
    assert quick("Drop S08.", cov)["ops"] == [{"op": "remove", "shot": "S08"}]
    assert quick("Remove S05, we don't need the master there.", cov)["ops"] == [{"op": "remove", "shot": "S05"}]
    assert quick("S04 to 8 seconds", cov)["ops"] == [{"op": "retime", "shot": "S04", "take_s": 8}]
    for message in ("Make S01 feel lonelier.", "Make S01 5 seconds.", "Drop S99.", "Why is S01 a medium?",
                    "Make the argument tenser."):
        assert quick(message, cov) is None, message


def test_a_call_gets_only_the_output_the_turn_can_afford() -> None:
    import pytest

    assert agents.output_cap("author", "sys", "user", 0.02) < agents.MODELS["author"][2]
    with pytest.raises(agents.OverBudget):
        agents.output_cap("author", "sys", " ".join(f"clip{i} holds" for i in range(15000)), 0.02)


def test_the_rehearsal_thread_accepts_undoes_rejects_and_refuses_a_stale_card() -> None:
    th = Thread(cov=scene())
    be = agents.Rehearsal(REHEARSAL)
    run_turn(th, "Drop S08.", be, "t04")
    assert th.card is not None and th.revision == 0
    r = run_turn(th, "[Accept]", be, "t05")
    assert r["saved"] and len(th.cov.clips) == 19
    run_turn(th, "Undo that.", be, "t06")
    assert len(th.cov.clips) == 20
    run_turn(th, "Remove S05, we don't need the master there.", be, "t07")
    run_turn(th, "Make S01 a wide, 6 seconds.", be, "t02")  # the scene changes while the card waits
    r = run_turn(th, "[Accept]", be, "t05")
    assert not r["saved"] and "scene changed" in r["status"]
