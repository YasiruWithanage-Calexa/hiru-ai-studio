"""Tests that live with the chat_answerer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.chat_answerer import agent
from hiru_ai.agents.chat_answerer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_facts_come_last_in_the_user_message():
    inp = Input.model_validate(CASES[0]["input"])
    message = agent.user_message(inp)
    assert message.rstrip().endswith("</turn>") and inp.turn[-1] in message.split("<turn>")[1]


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        Output(text=case["reply"])
