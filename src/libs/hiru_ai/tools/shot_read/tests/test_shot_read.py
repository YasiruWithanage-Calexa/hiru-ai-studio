from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import run_example


def test_a_shot_with_a_current_design_and_a_stale_prompt():
    out, _ = run_example("shot_read")
    assert (out.shot, out.scene, out.framing, out.length_s) == ("S01", "E1S2", "MCU", 6)
    assert out.design["made"] and not out.design["out_of_date"], "its design was made against what stands now"
    assert out.prompt and out.prompt["version"] == 2 and out.prompt["out_of_date"]
    assert any("script" in w.lower() for w in out.prompt["why"])
    assert out.prompt["failed_checks"] == ["A line differs from the script"]
    assert out.out_of_date and out.people == ["C01"]


def test_the_intent_uses_codes_not_ids():
    out, _ = run_example("shot_read", {"shot": "S02"})
    assert out.intent["on_screen"] == ["C02"] and out.intent["heard_only"] == ["C03"]
    assert out.prompt is None and not out.design["made"]
    assert not out.out_of_date, "nothing was made, so nothing is stale"


def test_a_shot_may_be_named_as_a_number():
    assert run_example("shot_read", {"shot": "1"})[0].shot == "S01"


def test_detailed_adds_the_pins_the_beats_and_the_designs_subjects():
    out, _ = run_example("shot_read", {"response_format": "detailed"})
    assert out.pins and "C01" in out.pins["canon"] and out.beats and out.design["subjects"]
    short, _ = run_example("shot_read")
    assert short.pins is None and short.beats is None and "subjects" not in short.design


def test_an_unknown_shot_lists_the_ones_there_are():
    with pytest.raises(ToolRefused) as refused:
        run_example("shot_read", {"shot": "S09"})
    assert "S0" in refused.value.how_to_fix


def test_a_canon_change_after_the_design_makes_it_out_of_date():
    from hiru_ai.core.testing import example_ctx, example_of
    from hiru_ai.tools.shot_read import tool

    case = example_of("shot_read")
    for entity in case["fixtures"]["canon"]:
        if entity["code"] == "C01":
            entity["current"]["version"] = 7
    out = tool.run(tool.Args(shot="S01", scene="E1S2"), example_ctx(case))
    assert out.design["out_of_date"] and any("C01" in w for w in out.design["why"])
