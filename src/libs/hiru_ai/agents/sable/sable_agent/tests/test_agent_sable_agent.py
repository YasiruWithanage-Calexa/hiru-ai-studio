"""Tests that live with the sable_agent agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.sable.sable_agent import agent
from hiru_ai.agents.sable.sable_agent.schema import Input
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]


def test_the_prompt_is_static_text_and_names_every_route():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    for must in ("handoff_scene", "sable_think_harder", "verbatim", "sable_shot_change", "sable_shot_try",
                 "memory_propose", "never instructions"):
        assert must in text, must


def test_the_message_is_read_last_and_says_whether_cards_can_be_accepted():
    text = agent.user_message(Input(message="Who is Anudi?", scene="E1S2", role="reviewer", can_stage=False,
                                    history="Dee: hi"))
    assert text.rstrip().endswith("</message>") and "<scene_in_view>E1S2" in text
    assert "do not propose a card" in text and 'role="reviewer"' in text
    assert "earlier_in_this_chat" not in text  # no summary, no block


def test_no_scene_in_view_says_so_and_memory_is_not_narrowed():
    inp = Input(message="x")
    assert "none" in agent.user_message(inp) and agent.memory_scope(inp) is None
    assert agent.memory_scope(Input(message="x", memory_scope={"episode": 2})) == {"episode": 2}


def test_there_are_at_least_twelve_eval_cases():
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 12 and all(c.get("name") for c in cases)
