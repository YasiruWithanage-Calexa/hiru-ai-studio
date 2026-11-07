"""Tests that live with the zora_reply agent (ADR 0006)."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.zora.zora_reply import agent
from hiru_ai.agents.zora.zora_reply.schema import Input
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]


def test_the_ledger_is_the_last_thing_the_model_reads():
    text = agent.user_message(Input(plan="PLAN", message="hi", turn=["DONE THIS TURN:\n- S03"], persona="You are X"))
    assert text.startswith("<persona>You are X</persona>\n<recent_chat>\n(none)\n</recent_chat>\n<plan>\nPLAN")
    assert text.endswith("<turn>\nTURN:\nDONE THIS TURN:\n- S03\n</turn>")


def test_the_prompt_never_lets_it_trim_or_mention_costs():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert "never trimmed" in text and "Never mention credits, costs or prices" in text


def test_there_are_eval_cases():
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 2
