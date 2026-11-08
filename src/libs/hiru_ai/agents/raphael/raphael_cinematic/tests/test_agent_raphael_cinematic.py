"""Tests that live with the raphael_cinematic agent (ADR 0006): deleting the folder deletes them. That the prompt is
the lab's
plus the variety lines is `tests/raphael/test_lab_parity.py`; the whole run is `tests/raphael/test_system.py`."""

from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.raphael.raphael_cinematic import agent
from hiru_ai.agents.raphael.raphael_cinematic.schema import Input
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def inp() -> Input:
    return Input.model_validate(CASES[0]["input"])


def test_the_prompt_is_static_text_with_the_rules_of_a_cinematic_clip():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    for rule in ("ANCHORED", "DIFFERENT FROM ITS ANCHOR", "SILENT", "VARIETY (D-V)", "At most 3 in any moment"):
        assert rule in text
    assert "$" not in text and "credit" not in text.lower()


def test_the_session_holds_stage_1s_clips_locked_and_numbers_the_next_clip_after_them():
    run = agent.session(inp())
    assert run.locked.keys() == {"c01"} and run.work.next_no == 2 and run.cap == 2
    assert run.max_turns == 8  # plan/2026-11-08f §4
    assert run.work.edit is not None and run.changed_must() == []


def test_the_tools_are_stage_2s_and_a_conversation_is_built_from_the_input():
    args = agent.converse_args(inp(), agent.session(inp()))
    assert [t["function"]["name"] for t in args["tools"]] == ["put_extras", "remove_extras", "read_bin", "finish"]
    assert all(t["function"]["strict"] is True and "$ref" not in str(t) for t in args["tools"])
    finish = next(t for t in args["tools"] if t["function"]["name"] == "finish")["function"]["parameters"]
    assert list(finish["properties"]) == ["blend_notes", "moment_review"]


def test_the_user_message_is_the_opening_as_it_stands():
    assert agent.user_message(inp()) == inp().opening


def test_there_are_eval_cases():
    assert len(CASES) >= 2 and all(c.get("name") for c in CASES)
