from __future__ import annotations

from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.scene_reading_read import tool


def test_only_the_stretch_asked_for_comes_back():
    out, _ = run_example("scene_reading_read")
    assert out.about.startswith("A smile") and out.blocks == "2-5"
    assert [u["from_block"] for u in out.units] == [2]
    assert [h["after_block"] for h in out.holds] == [5] and out.holds[0]["who"] == "Anudi"
    assert [m["who"] for m in out.marks] == ["Anudi"] and out.zones == ["stall", "street"]


def test_the_whole_scene_when_no_stretch_is_given():
    out, _ = run_example("scene_reading_read", {"from_block": None, "to_block": None})
    assert out.blocks == "0-end" and len(out.units) == 2 and len(out.marks) == 2


def test_internal_anchors_are_left_out_until_detailed():
    out, _ = run_example("scene_reading_read")
    assert "anchor" not in out.holds[0] and "anchor" not in out.marks[0]
    full, _ = run_example("scene_reading_read", {"response_format": "detailed"})
    assert "anchor" in full.holds[0] and "anchor" in full.marks[0]


def test_a_scene_with_no_reading_says_so_instead_of_failing():
    case = example_of("scene_reading_read")
    case["fixtures"]["scenes"][0]["reading"] = {}
    case["fixtures"]["scenes"][0]["staging"] = {}
    out = tool.run(tool.Args(), example_ctx(case))
    assert not out.has_reading and not out.has_staging and out.units == [] and out.marks == []
