"""Tests that live with the raphael_breakdown agent (ADR 0006): deleting the folder deletes them."""

from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.raphael.raphael_breakdown import agent
from hiru_ai.agents.raphael.raphael_breakdown.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text() -> None:
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_message_is_the_opening_then_the_ask_and_a_retry_lists_the_faults() -> None:
    first = agent.user_message(Input(opening="<script>x</script>"))
    assert first.startswith("<script>x</script>") and first.endswith(agent.ASK)
    again = agent.user_message(Input(opening="<script>x</script>", faults=["Block 3 is in no shot."]))
    assert again.startswith(first) and "- Block 3 is in no shot." in again


def test_the_eval_replies_are_valid_outputs() -> None:
    for case in CASES:
        Output.model_validate(case["reply"])
