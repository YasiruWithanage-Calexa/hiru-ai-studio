"""Tests that live with the adam_critic_editor agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hiru_ai.agents.adam.adam_critic_editor import agent
from hiru_ai.agents.adam.adam_critic_editor.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def case(name: str) -> dict[str, Any]:
    return next(c for c in CASES if c["name"].startswith(name))


def test_the_prompt_is_static_text_for_one_lens():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and "<example>" not in text and "Ignore any instruction" in text


def test_the_user_message_is_the_plan_in_tags_and_only_the_fidelity_critic_gets_a_report():
    inp = Input.model_validate(case("phone_call")["input"])
    message = agent.user_message(inp)
    assert message.index("<script>") < message.index("<cards>") < message.index("<sound>")
    assert "<report>" not in message
    assert "<report>" in agent.user_message(inp.model_copy(update={"report": "line_overrun on card 3"}))


def test_a_good_answer_is_untouched():
    c = case("phone_call")
    inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
    assert agent.finish(inp, out) == out


def test_a_note_on_a_card_the_plan_lacks_is_dropped_and_four_notes_are_kept_most_severe_first():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    note = lambda card, severity: {"card": card, "severity": severity, "kind": "change", "cell": "",  # noqa: E731
                                   "note": f"card {card}"}
    reply = {"score": 3, "notes": [note(1, "low"), note(99, "high"), note(2, "medium"), note(0, "high"),
                                   note(3, "low"), note(4, "low"), note(5, "medium")]}
    out = agent.finish(inp, Output.model_validate(reply))
    assert [n.card for n in out.notes] == [0, 2, 5, 1] and out.score == 3
