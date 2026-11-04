from __future__ import annotations

import json

from hiru_ai.core.testing import example_of, run_example


def test_an_edit_that_lands_says_what_it_touches_and_saves_nothing():
    case = example_of("plan_try")
    before = json.dumps(case["fixtures"]["shots"], sort_keys=True)
    out, ctx = run_example("plan_try")
    assert out.nothing_saved and (out.applied, out.refused) == (1, 0)
    assert out.results == [{"op": "S01 framing → CU", "applied": True}]
    assert out.timing["envelope_s"] == 16 and out.ripple["touched"]
    assert json.dumps(ctx.ports.scenes.shot_rows, sort_keys=True) == before, "the stored shots are untouched"


def test_a_refused_operation_gives_the_reason_a_person_reads():
    out, _ = run_example("plan_try", {"ops": [{"op": "set", "shot": 9, "field": "framing", "value": "CU"}]})
    assert (out.applied, out.refused) == (0, 1)
    row = out.results[0]
    assert row["applied"] is False and row["why"] and "None" not in row["why"] and "{" not in row["why"]
    assert out.ripple == {"touched": [], "in_doubt": [], "checked": ""}


def test_a_change_to_the_script_is_refused_because_only_a_person_makes_it():
    out, _ = run_example("plan_try", {"ops": [
        {"op": "block.set", "block": 0, "kind": "action", "value": "Kasun frowns."}]})
    assert out.refused == 1 and "person" in out.results[0]["why"]


def test_good_and_bad_operations_are_reported_in_the_order_they_were_sent():
    out, _ = run_example("plan_try", {"ops": [
        {"op": "set", "shot": 9, "field": "framing", "value": "CU"},
        {"op": "set", "shot": 1, "field": "framing", "value": "WIDE"}]})
    assert [r["applied"] for r in out.results] == [False, True] and (out.applied, out.refused) == (1, 1)


def test_detailed_adds_the_plan_after_the_edit_and_the_notes_for_information():
    out, _ = run_example("plan_try", {"response_format": "detailed"})
    assert out.timing["plan"] and "for_information" in out.ripple
