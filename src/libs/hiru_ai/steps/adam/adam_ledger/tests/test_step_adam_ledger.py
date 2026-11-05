"""adam_ledger: a moment never leaves the plan without a record (plan/2026-11-04c F1)."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.adam.adam_ledger import step

HERE = Path(__file__).resolve().parents[1]


def test_the_example_closes_the_books():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["ok"] and out["problems"] == []
    assert out["buckets"] == {"kept": ["m1", "m2", "m5"], "dropped_fidelity": ["m3"], "removed_by_person": [],
                              "removed_by_operation": ["m4"]}


def test_a_moment_in_no_bucket_fails_with_its_id_in_plain_words():
    out = step.run({"created": ["m7", "m8"], "final": ["m7"]})
    assert not out["ok"] and out["unaccounted"] == ["m8"]
    assert out["problems"] == ["moment m8 left the plan without a record"]


def test_a_removal_that_names_no_note_is_not_a_record():
    out = step.run({"created": ["m8"], "final": [], "removed_by_operation": [{"id": "m8", "op": "operation 3",
                                                                                 "note_id": ""}]})
    assert not out["ok"] and "answers no note" in out["problems"][0]


def test_a_moment_in_two_buckets_is_refused():
    out = step.run({"created": ["m2"], "final": ["m2"], "removed_by_person": ["m2"]})
    assert not out["ok"] and out["doubled"] == ["m2"]


def test_a_person_removal_is_a_record():
    out = step.run({"created": ["m2", "m3"], "final": ["m3"], "removed_by_person": ["m2"]})
    assert out["ok"] and out["buckets"]["removed_by_person"] == ["m2"]


def test_moments_a_revision_added_are_listed_not_reconciled():
    out = step.run({"created": ["m1"], "final": ["m1", "r1"]})
    assert out["ok"] and out["added"] == ["r1"]


def test_nothing_made_is_a_closed_book():
    assert step.run({})["ok"]
