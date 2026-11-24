"""Tests that live with the views_writer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.views_writer import agent
from hiru_ai.agents.views_writer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_message_carries_the_place_and_what_stands_in_it():
    text = agent.user_message(Input.model_validate(CASES[0]["input"]))
    assert "Colombo roadside" in text and "Food three-wheeler" in text and "vending bay" in text


def test_the_eval_replies_are_valid_outputs_with_six_views():
    for case in CASES:
        out = Output.model_validate(case["reply"])
        assert len(out.views) == 6 and out.views[0].name == "Front wide"
