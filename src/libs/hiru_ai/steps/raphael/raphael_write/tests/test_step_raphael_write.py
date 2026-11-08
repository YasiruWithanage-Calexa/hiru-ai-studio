"""Tests that live with the raphael_write step (ADR 0006): deleting the folder deletes them. The whole-system checks
are in
`tests/raphael`."""

from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.raphael.raphael_write import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_is_written_as_a_shot_per_clip_with_a_current_design_and_the_lines_bound():
    out = step.run(EXAMPLE)
    shots = out["shots"]
    assert len(shots) == 21 and all(s["planner"] == "raphael" and s["ir"] and s["design"]["pins"] for s in shots)
    assert all(s["intent"]["by"] == "raphael" for s in shots) and out["fields"]["coverage"]["by"] == "raphael"
    assert sum(1 for ln in out["lines"] if ln["shot_id"]) == len(EXAMPLE["lines"])
    assert [s["number"] for s in shots] == list(range(1, 22))
    assert sum(1 for s in shots if s["stage"] == 2) == 8 and out["fields"]["raphael"]["planner"] == "raphael"


def test_an_approved_scene_is_refused():
    approved = {**EXAMPLE, "scene": {**EXAMPLE["scene"], "status": "approved"}}
    assert "refused" in step.run(approved)


def test_a_result_that_cannot_be_read_says_so_instead_of_raising():
    assert "malformed" in step.run({**EXAMPLE, "stored": {"clips": "nope"}})
