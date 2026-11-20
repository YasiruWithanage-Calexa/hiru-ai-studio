"""Tests that live with the video_prompter agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts import safe_depiction
from hiru_ai.agents.video_prompter import agent
from hiru_ai.agents.video_prompter.schema import Direction, Input
from hiru_ai.core import agents
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_and_carries_the_hard_rules():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert safe_depiction.PROMPT_LINE in text  # every writer of what a shot shows (plan/2026-11-10b)
    assert "Never write Sinhala" in text and "locked-off camera stays locked off" in text


def test_the_scene_goes_first_as_its_own_message_then_the_clip_then_the_cards():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.shared_message(inp) == inp.scene  # the same bytes for every clip of the scene: it caches
    msg = agent.user_message(inp)
    assert msg.startswith("<clip") and "<cards>" in msg and "CARD: PEOPLE TALKING ON SCREEN" in msg
    assert "<scene>" not in msg
    call = agents.build("video_prompter").prepare(inp)
    assert call.shared == inp.scene and call.user.startswith("<clip")


def test_a_repair_shows_the_first_answer_and_exactly_the_faults():
    inp = Input.model_validate({**CASES[0]["input"], "repair": ["camera: the planner's camera is locked off"],
                                "previous": '{"camera": "a push-in"}'})
    msg = agent.user_message(inp)
    assert '<your_first_answer>\n{"camera": "a push-in"}' in msg and "- camera: the planner's camera" in msg


def test_every_card_the_step_can_pick_exists():
    for name in agent.CARD_NAMES:
        assert agent.card(name).startswith("CARD:")
    assert agent.card("nothing") == ""


def test_without_a_model_there_is_no_answer_and_no_fallback():
    with pytest.raises(ModelUnavailable):
        agents.build("video_prompter").run(Input.model_validate(CASES[0]["input"]), RunContext())


def test_the_eval_replies_are_valid_answers():
    assert len(CASES) >= 5
    for case in CASES:
        Direction.model_validate(case["reply"])
