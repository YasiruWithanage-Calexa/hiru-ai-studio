"""Tests that live with the jonathan_mend step (ADR 0006): deleting the folder deletes them. The gold-scene checks are
in
`tests/jonathan`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.jonathan.jonathan_mend import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_plan_is_left_as_it_is():
    out = step.run(EXAMPLE)
    assert out["plan"] == EXAMPLE["plan"] and out["mended"] == [] and out["dropped"] == []


def test_a_take_too_short_for_its_line_is_made_longer_and_the_line_is_never_touched():
    plan = json.loads(json.dumps(EXAMPLE["plan"]))
    plan["shots"][6]["take_s"] = 4  # the father's line, played over Anudi
    out = step.run({"scene": EXAMPLE["scene"], "plan": plan})
    assert out["plan"]["shots"][6]["take_s"] == 6 and out["plan"]["shots"][6]["lines"] == ["L4"]
    assert any("6 s take" in line for line in out["mended"])
