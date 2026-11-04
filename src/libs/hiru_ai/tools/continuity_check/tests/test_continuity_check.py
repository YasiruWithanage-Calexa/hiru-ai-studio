from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.continuity_check import tool


def test_the_first_join_of_the_example_scene_is_clean():
    out, _ = run_example("continuity_check")
    assert (out.first, out.second, out.join) == ("S01", "S02", "cut") and out.ok and out.staging_map


def test_the_last_shot_has_no_join_and_says_so():
    out, _ = run_example("continuity_check", {"shot": "S02"})
    assert out.second is None and out.ok and "last shot" in out.note


def test_a_continuing_shot_in_another_size_is_reported_in_words():
    case = example_of("continuity_check")
    case["fixtures"]["shots"][1].update(camera_link="continuous", framing="WIDE")
    out = tool.run(tool.Args(shot="S01"), example_ctx(case))
    assert not out.ok and out.findings[0]["code"] == "join_size" and "WIDE" in out.findings[0]["message"]
    assert set(out.findings[0]) == {"code", "message"}, "concise leaves the names out"
    full = tool.run(tool.Args(shot="S01", response_format="detailed"), example_ctx(case))
    assert "who" in full.findings[0]


def test_an_unknown_shot_lists_the_shots_there_are():
    with pytest.raises(ToolRefused) as refused:
        run_example("continuity_check", {"shot": "S07"})
    assert "S01" in refused.value.how_to_fix
