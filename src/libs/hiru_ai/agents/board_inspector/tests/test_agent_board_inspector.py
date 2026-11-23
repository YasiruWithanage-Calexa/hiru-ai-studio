"""Tests that live with the board_inspector agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.board_inspector import agent
from hiru_ai.agents.board_inspector.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_message_names_the_mannequins_and_the_hands():
    inp = Input.model_validate(CASES[0]["input"])
    text = agent.user_message(inp)
    assert "Anudi is the blue mannequin" in text and "HANDS: Hands: the blue mannequin" in text
    assert agent.images(inp) == [("image/png", "iVBORw0KGgo=")]
    assert "HANDS" not in agent.user_message(Input.model_validate(CASES[1]["input"])), "no hands, no hand check"


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])
