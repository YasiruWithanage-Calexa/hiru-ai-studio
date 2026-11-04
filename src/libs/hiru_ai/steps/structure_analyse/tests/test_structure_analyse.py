"""The analysis is the legacy engine's, unchanged."""
from __future__ import annotations

import json
from pathlib import Path

from structure_build.engine import analyse as legacy

from hiru_ai.steps.structure_analyse import step

HERE = Path(__file__).resolve().parents[1]


def test_the_plan_and_the_structure_equal_the_legacy_ones():
    case = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    plan = legacy.analyse(case["documents"], case["canon"])
    got = step.run(case)["plan"]
    assert json.dumps(got, sort_keys=True, default=str) == json.dumps(plan, sort_keys=True, default=str)
    assert [q["key"] for q in got["questions"]] == ["episode:d1:0"]  # an episode the file does not number is asked
    answers = legacy.default_answers(plan["questions"])
    assert step.run({"op": "default_answers", "questions": plan["questions"]})["answers"] == answers
    structure = step.run({"op": "apply_answers", "plan": plan, "answers": answers, "canon": case["canon"]})
    assert json.dumps(structure["structure"], sort_keys=True, default=str) == json.dumps(
        legacy.apply_answers(plan, answers, case["canon"]), sort_keys=True, default=str)
