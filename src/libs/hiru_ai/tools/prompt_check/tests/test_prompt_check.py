from __future__ import annotations

import pytest

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import run_example


def test_the_example_prompt_has_everything_wrong_that_the_lint_knows():
    out, _ = run_example("prompt_check")
    codes = [f["code"] for f in out.findings]
    assert out.version == 2 and not out.ok
    assert {"missing_section", "duration", "line_changed", "failed_check"} <= set(codes)
    assert any("constraints" in f["message"] for f in out.findings)
    assert any("8 seconds" in f["message"] for f in out.findings)


def test_a_shot_with_no_prompt_has_nothing_to_check():
    with pytest.raises(ToolRefused) as refused:
        run_example("prompt_check", {"shot": "S02"})
    assert "no prompt yet" in str(refused.value) and refused.value.how_to_fix


def test_only_the_latest_version_can_be_checked():
    assert run_example("prompt_check", {"version": 2})[0].version == 2
    with pytest.raises(ToolRefused, match="v1 is not kept"):
        run_example("prompt_check", {"version": 1})


def test_detailed_counts_the_words():
    out, _ = run_example("prompt_check", {"response_format": "detailed"})
    assert out.words and run_example("prompt_check")[0].words is None
