"""Tests that live with the prompt_writer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.prompt_writer import agent
from hiru_ai.agents.prompt_writer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_message_carries_each_section_and_what_it_must_keep():
    inp = Input.model_validate(CASES[0]["input"])
    msg = agent.user_message(inp)
    assert "ONE STILL FRAME" in msg and '"key": "light"' in msg and '"keep": ["3800K"]' in msg


def test_without_a_model_every_section_comes_back_as_code_wrote_it():
    inp = Input.model_validate(CASES[1]["input"])
    assert agent.fallback(inp).model_dump() == {"sections": [{"key": "camera", "text": inp.sections[0].text}]}


def test_the_eval_replies_are_valid_outputs():
    assert len(CASES) >= 2 and all(c.get("name") for c in CASES)
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])
