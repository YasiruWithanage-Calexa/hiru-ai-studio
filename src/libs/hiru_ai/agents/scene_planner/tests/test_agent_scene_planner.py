"""Tests that live with the scene_planner agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.scene_planner import agent
from hiru_ai.agents.scene_planner.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    assert Prompt.load(HERE / "prompts" / "system.md").text.strip()


def test_the_hooks_use_the_agents_own_types():
    inp = Input.model_validate(CASES[0]["input"])
    assert isinstance(agent.user_message(inp), str)
    answer = agent.fallback(inp) if hasattr(agent, "fallback") else None
    assert answer is None or isinstance(answer, Output)


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])
