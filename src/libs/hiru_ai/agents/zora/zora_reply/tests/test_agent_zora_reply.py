"""Tests that live with the zora_reply agent (ADR 0006)."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.zora.zora_reply import agent
from hiru_ai.agents.zora.zora_reply.schema import Input
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]


def test_the_facts_are_the_last_thing_the_model_reads():
    text = agent.user_message(Input(scene="SCENE", message="hi", facts=["WHAT CHANGED:\n- S03's lens is now 85mm"],
                                    persona="You are Zora"))
    assert text.startswith("<persona>You are Zora</persona>\n<recent_chat>\n(none)\n</recent_chat>\n<scene>\nSCENE")
    assert text.endswith("(the truth; it outranks the conversation):\nWHAT CHANGED:\n- S03's lens is now 85mm\n</turn>")


def test_the_prompt_never_lets_it_trim_or_mention_costs_or_a_reshoot():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert "never trimmed" in text and "Never mention credits, costs or prices" in text and "reshoot" in text


def test_there_are_eval_cases():
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 2
