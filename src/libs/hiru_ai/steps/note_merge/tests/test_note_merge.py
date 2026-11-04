"""The merge is the legacy critic's, unchanged."""
from __future__ import annotations

import json
from pathlib import Path

from script_split.engine import critic

from hiru_ai.steps.note_merge import step
from hiru_ai.steps.note_merge.logic import merge_notes, notes_of

HERE = Path(__file__).resolve().parents[1]


def test_it_merges_exactly_as_the_legacy_critic_did():
    case = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    rounds = [critic._notes(c) if c is not None else [] for c in case["critics"]]
    assert step.run(case)["notes"] == critic.merge_notes(rounds)
    assert step.run(case)["notes"] == ["S02 needs Kamala's reaction", "Cut on the look", "Vary the sizes"]


def test_a_content_critic_has_no_notes_and_a_bad_severity_is_two():
    assert notes_of({"acceptable": True, "notes": [{"note": "x", "severity": 1}]}) == []
    assert notes_of({"acceptable": False, "notes": ["plain", {"note": "y", "severity": 9}]}) == [(2, "plain"), (2, "y")]


def test_a_critic_that_failed_is_left_out_and_all_failing_is_reported():
    assert step.run({"critics": [None, {"acceptable": False, "notes": ["a"]}]}) == {"notes": ["a"], "all_failed": False}
    assert step.run({"critics": [None, None]}) == {"notes": [], "all_failed": True}


def test_at_most_the_limit_and_each_note_once():
    many = [[(2, f"note {i}") for i in range(4)], [(2, "NOTE 0")]]
    assert len(merge_notes(many)) == 4 and merge_notes(many, limit=2) == ["note 0", "note 1"]
