"""Tests that live with the story_reader agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.story_reader import agent
from hiru_ai.agents.story_reader.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_document_is_wrapped_as_data_and_cut_at_the_limit():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.user_message(inp).startswith('<document name="scene.md"')
    long = Input(filename="long.txt", text="a" * (agent.MAX_DOC_CHARS + 500))
    assert "a" * agent.MAX_DOC_CHARS in agent.user_message(long)
    assert "a" * (agent.MAX_DOC_CHARS + 1) not in agent.user_message(long)


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])
