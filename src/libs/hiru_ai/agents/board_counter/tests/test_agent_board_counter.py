"""Tests that live with the board_counter agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import yaml

from hiru_ai.agents.board_counter import agent
from hiru_ai.agents.board_counter.schema import Input, Output
from hiru_ai.core import agents
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_and_never_asks_what_should_be_there():
    text = " ".join(Prompt.load(HERE / "prompts" / "system.md").text.split())
    assert "Report only what you SEE, never what a person should have." in text
    assert "HANDS" not in text and "SHOULD SHOW" not in text


def test_the_message_names_only_the_colours_and_sends_only_the_panel():
    """lab/board_hands R5: the blind look is told the colours and nothing else (R0-R3 copied the expected hands)."""
    inp = Input.model_validate(CASES[1]["input"])
    assert agent.user_message(inp) == "MANNEQUINS IN THIS PANEL:\n- the red mannequin\n- the blue mannequin"
    assert agent.images(inp) == [("image/png", "iVBORw0KGgo=")]


def test_the_eval_replies_are_valid_outputs():
    for case in CASES:
        if "reply" in case:
            Output.model_validate(case["reply"])


def test_it_sees_the_pictures_at_high_detail_and_others_stay_low():
    """plan/2026-11-25 B1: the counter asks for `high` (lab R5); every other picture agent keeps `low`."""
    call = agents.build("board_counter").prepare(Input.model_validate(CASES[1]["input"]))
    assert call.image_detail == "high"
    assert agents.build("board_inspector").manifest.image_detail == "low"
