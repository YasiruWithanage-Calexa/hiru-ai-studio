from __future__ import annotations

import pytest

from contracts import sceneplan
from contracts.shotplan import fit
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_of, run_example


def test_the_stored_plan_is_fitted_by_the_kernel():
    out, ctx = run_example("timing_check")
    scene = ctx.ports.scenes.scene_rows[0]
    items = sceneplan.scene_items(scene, ctx.ports.scenes.line_rows)
    expected = fit(items, sceneplan.proposal_for(sceneplan.plan_from_rows(ctx.ports.scenes.shot_rows)),
                   envelope_s=int(scene["envelope_s"]))
    assert out.scene == "E1S2" and out.total_s == expected.total_s
    assert [s["length_s"] for s in out.shots] == [s.duration_s for s in expected.shots]
    assert [i["code"] for i in out.issues] == [i.code for i in expected.issues]


def test_each_lines_start_and_overrun_are_answered():
    out, _ = run_example("timing_check")
    assert next(ln["shot"] for ln in out.lines) == "S01" and len(out.lines) == 2
    assert all("starts_s" in ln and "overrun_s" in ln for ln in out.lines)


def test_a_plan_being_thought_about_is_checked_before_it_is_saved():
    out, _ = run_example("timing_check", {"shots": [{"start": 0, "end": 6, "framing": "WIDE"}]})
    assert len(out.shots) >= 1 and out.shots[0]["start_s"] == 0
    detailed, _ = run_example("timing_check", {"shots": [{"start": 0, "end": 6, "framing": "WIDE"}],
                                              "response_format": "detailed"})
    assert detailed.shots[0]["framing"] == "WIDE" and detailed.shots[0]["blocks"].startswith("0-")


def test_a_fixed_length_makes_every_shot_that_long_and_overruns_are_reported_not_trimmed():
    out, _ = run_example("timing_check", {"fixed_seconds": 4})
    assert {s["length_s"] for s in out.shots} == {4}


def test_a_scene_that_is_not_there_is_refused_with_the_names_that_are():
    with pytest.raises(ToolRefused) as refused:
        run_example("timing_check", {"scene": "E1S9"})
    assert "E1S2" in refused.value.how_to_fix


def test_the_example_checks_the_scene_it_names():
    assert example_of("timing_check")["args"]["scene"] == "E1S2"
