from __future__ import annotations

from hiru_ai.core.testing import run_example
from hiru_ai.tools.plan_score import tool

TWO = [{"start": 0, "end": 2, "framing": "MCU"}, {"start": 2, "end": 6, "framing": "MCU"}]
ONE = [{"start": 0, "end": 6, "framing": "WIDE"}]


def test_the_score_is_named_part_by_part():
    out, _ = run_example("plan_score")
    assert out.lower_is_better and list(out.parts) == list(tool.PARTS) and len(out.score) == len(tool.PARTS)
    assert out.plan is None and out.scene == "E1S2"


def test_two_plans_can_be_compared_part_by_part_from_the_first():
    a, _ = run_example("plan_score", {"shots": TWO})
    b, _ = run_example("plan_score", {"shots": ONE})
    assert a.score != b.score and a.total_s > 0 and b.total_s > 0
    assert tuple(a.score) <= tuple(a.score)


def test_detailed_adds_the_plan_as_the_kernel_describes_it():
    out, _ = run_example("plan_score", {"response_format": "detailed"})
    assert out.plan and "Envelope: 16 s" in out.plan
