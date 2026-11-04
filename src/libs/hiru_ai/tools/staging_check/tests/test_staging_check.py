from __future__ import annotations

import pytest
from tests.hiru_ai.steps_fixtures import run_ctx, teleporting_scene

from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.staging_check import tool


def test_a_scene_whose_people_stay_put_has_no_findings():
    out, _ = run_example("staging_check")
    assert out.has_staging_map and out.ok and out.findings == [] and out.fixes == []


def test_a_person_who_teleports_is_found_with_the_move_that_would_fix_it():
    scene, lines, shots = teleporting_scene()
    out = tool.run(tool.Args(scene="E1S2"), run_ctx(scene, lines, shots))
    assert not out.ok and out.findings[0]["code"] == "teleport" and "Anudi" in out.findings[0]["message"]
    assert out.fixes and out.fixes[0]["who"].casefold() == "anudi"


def test_a_scene_with_no_staging_map_has_no_findings_and_says_so():
    case = example_of("staging_check")
    case["fixtures"]["scenes"][0]["staging"] = {}
    out = tool.run(tool.Args(), example_ctx(case))
    assert out.ok and not out.has_staging_map


def test_a_plan_being_thought_about_is_checked_instead_of_the_stored_one():
    out, _ = run_example("staging_check", {"shots": [{"start": 0, "end": 6, "framing": "WIDE"}]})
    assert isinstance(out.findings, list)


@pytest.mark.parametrize("fmt", ["concise", "detailed"])
def test_both_formats_answer(fmt: str):
    assert run_example("staging_check", {"response_format": fmt})[0].scene == "E1S2"
