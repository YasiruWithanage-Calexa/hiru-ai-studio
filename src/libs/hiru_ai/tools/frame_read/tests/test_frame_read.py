from __future__ import annotations

import pytest
from pydantic import ValidationError

from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of, run_example
from hiru_ai.tools.frame_read import tool


def test_a_shots_frames_say_whether_one_is_accepted_and_whether_it_is_out_of_date():
    out, _ = run_example("frame_read", {"code": None})
    (frame,) = out.frames
    assert frame["shot"] == "S01" and frame["status"] == "done" and frame["accepted"]
    assert frame["out_of_date"] and any("script" in w.lower() for w in frame["why"])
    assert out.sheets == []


def test_a_codes_sheets_and_looks_are_counted_never_linked():
    out, _ = run_example("frame_read", {"shot": None})
    (sheet,) = out.sheets
    assert sheet["code"] == "C02" and sheet["looks"] == [
        {"name": "Office whites", "status": "ready", "sheets": 1, "ranges": [{"from": 1, "to": 3}]}]
    assert "references/" not in str(out.model_dump()), "a storage path never leaves the port"


def test_one_of_shot_or_code_is_needed():
    with pytest.raises(ValidationError, match="pass `shot`"):
        tool.Args()


def test_an_unknown_code_lists_the_closest():
    with pytest.raises(ToolRefused) as refused:
        run_example("frame_read", {"shot": None, "code": "Anudy"})
    assert "Anudi" in refused.value.how_to_fix


def test_a_shot_with_no_frames_has_an_empty_list():
    case = example_of("frame_read")
    case["fixtures"]["frames"] = []
    out = tool.run(tool.Args(shot="S02"), example_ctx(case))
    assert out.frames == []
