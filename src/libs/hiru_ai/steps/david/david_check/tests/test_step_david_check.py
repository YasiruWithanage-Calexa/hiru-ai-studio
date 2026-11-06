"""Tests that live with the david_check step (ADR 0006): deleting the folder deletes them. The gold-scene checks are in
`tests/david`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.david.david_check import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_plan_passes_and_a_plan_that_cannot_be_read_says_so_instead_of_raising():
    out = step.run(EXAMPLE)
    assert out["ok"] and out["problems"] == []
    bad = step.run({"scene": EXAMPLE["scene"], "plan": {"shots": "nope"}})
    assert not bad["ok"] and bad["problems"][0]["code"] == "shape"


def test_a_dropped_line_is_a_problem_for_the_author_to_repair():
    plan = json.loads(json.dumps(EXAMPLE["plan"]))
    plan["shots"][1]["lines"] = []
    out = step.run({"scene": EXAMPLE["scene"], "plan": plan})
    assert not out["ok"] and out["counts"]["repair"] >= 1
