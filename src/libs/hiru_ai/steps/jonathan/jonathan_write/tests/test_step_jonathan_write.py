"""Tests that live with the jonathan_write step (ADR 0006): deleting the folder deletes them. The gold-scene checks are
in
`tests/jonathan`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.jonathan.jonathan_write import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_is_written_as_shots_with_a_current_design_and_the_lines_bound():
    out = step.run(EXAMPLE)
    shots = out["shots"]
    assert len(shots) == 15 and all(s["planner"] == "jonathan" and s["ir"] and s["design"]["pins"] for s in shots)
    assert all(s["intent"]["by"] == "jonathan" for s in out["shots"]) and out["fields"]["coverage"]["by"] == "jonathan"
    assert sum(1 for ln in out["lines"] if ln["shot_id"]) == 4


def test_an_approved_scene_is_refused():
    approved = {**EXAMPLE, "scene": {**EXAMPLE["scene"], "status": "approved"}}
    assert "refused" in step.run(approved)


def test_a_plan_that_cannot_be_read_says_so_instead_of_raising():
    assert "malformed" in step.run({**EXAMPLE, "stored": {"plan": "nope"}})
