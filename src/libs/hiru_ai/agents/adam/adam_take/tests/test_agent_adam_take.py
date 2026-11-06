"""Tests that live with the adam_take agent (ADR 0006): deleting the folder deletes them. The gold-set checks (the one
answer rebuilds every master and passes every code rule) are in `tests/adam/test_take.py`."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hiru_ai.agents.adam.adam_take import agent
from hiru_ai.agents.adam.adam_take.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def case(name: str) -> dict[str, Any]:
    return next(c for c in CASES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "4, 6 or 8" in text


def test_the_user_message_is_the_script_then_the_facts_and_nothing_a_switch_would_add():
    message = agent.user_message(Input.model_validate(case("phone_call")["input"]))
    assert message.index("<context>") < message.index("<script>") < message.index("<facts>")
    assert "<given_analysis>" not in message and "<stance>" not in message and "<notes>" not in message


def test_every_eval_reply_is_a_take_that_builds_into_the_plans_parts():
    for c in CASES:
        built = Output.model_validate(c["reply"]).plan()
        assert built.cards and built.moments and [x.number for x in built.cards] == list(range(1, len(built.cards) + 1))
        assert len(built.alternates) == 2 and built.treatment.stance


def test_the_manifest_asks_for_the_timeout_an_answer_of_this_size_needs():
    from hiru_ai.core import agents

    assert agents.build("adam_take").manifest.timeout_s == 600
