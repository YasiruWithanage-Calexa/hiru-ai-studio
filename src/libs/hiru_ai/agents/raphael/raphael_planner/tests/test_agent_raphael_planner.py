"""Tests that live with the raphael_planner agent (ADR 0006): deleting the folder deletes them. That the prompt is the
lab's is
`tests/raphael/test_lab_parity.py`; the whole run is `tests/raphael/test_system.py`."""

from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.raphael.raphael_planner import agent
from hiru_ai.agents.raphael.raphael_planner.schema import Input
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_that_asks_for_must_clips_only():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert "THE MUST BIN" in text and "Every clip is `must`" in text and "second stage" in text
    assert "$" not in text and "credit" not in text.lower()


def test_the_user_message_is_the_opening_as_it_stands():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.user_message(inp) == inp.opening


def test_the_session_and_the_conversation_are_built_from_the_input():
    inp = Input.model_validate(CASES[0]["input"])
    run = agent.session(inp)
    args = agent.converse_args(inp, run)
    assert [t["function"]["name"] for t in args["tools"]] == [
        "write_edit_plan",
        "put_clips",
        "remove_clips",
        "read_bin",
        "finish",
    ]
    assert args["max_turns"] == 10 and not run.done  # plan/2026-11-08f §4
    assert args["later_tier"] == "raphael_repair"  # the repair turns at their own effort (§5)
    args["before"](3)
    assert run.turn == 3  # the report says how many turns are left


def test_every_tool_is_strict_and_has_no_open_reference():
    for spec in agent.converse_args(
        Input.model_validate(CASES[0]["input"]), agent.session(Input.model_validate(CASES[0]["input"]))
    )["tools"]:
        assert spec["function"]["strict"] is True and "$ref" not in str(spec)
    schema = next(
        t
        for t in agent.converse_args(
            Input.model_validate(CASES[0]["input"]), agent.session(Input.model_validate(CASES[0]["input"]))
        )["tools"]
        if t["function"]["name"] == "put_clips"
    )["function"]["parameters"]
    assert "ir" in schema["properties"]["clips"]["items"]["properties"]
    assert schema["properties"]["clips"]["items"]["properties"]["take_s"]["enum"] == [4, 6, 8]


def test_there_are_eval_cases():
    assert len(CASES) >= 2 and all(c.get("name") for c in CASES)
