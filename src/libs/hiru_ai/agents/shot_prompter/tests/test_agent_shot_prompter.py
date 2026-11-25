"""Tests that live with the shot_prompter agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts import safe_depiction
from hiru_ai.agents.shot_prompter import agent
from hiru_ai.agents.shot_prompter.schema import Input, ShotPrompts
from hiru_ai.core import agents
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_and_carries_the_hard_rules():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert safe_depiction.PROMPT_LINE in text  # every writer of what a shot shows (plan/2026-11-10b)
    assert "Never write Sinhala" in text and "Never name camera gear" in text
    assert "A still has NO motion" in text and "VIDEO ONLY" in text
    assert "never write\nclock or edit words" in text or "clock or edit words" in " ".join(text.split())


def test_the_prompt_gives_the_lengths_code_checks_and_the_boards_word_for_a_held_thing():
    """2026-11-25: 13 of 14 first answers of a scene failed a check the prompt never stated (`video.people` 700-1000
    characters against 650) or named the board's phone a "handset", and each paid a repair call."""
    from hiru_ai.core import parts

    limits = parts.step("shot_prompt", "logic").LIMITS
    text = " ".join(Prompt.load(HERE / "prompts" / "system.md").text.split())
    assert f"`situation` at most {limits['situation']}" in text
    assert f"`people` at most {limits['people']}" in text
    assert f"`sound` at most {limits['sound']}" in text
    assert f"`listener` at most {limits['step']} each" in text
    assert f"together at most {limits['frame']}" in text
    assert "in the board's own word for it" in text


def test_the_scene_goes_first_as_its_own_message_then_the_shot_the_camera_and_the_cards():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.shared_message(inp) == inp.scene  # the same bytes for every shot of the scene: it caches
    msg = agent.user_message(inp)
    assert msg.startswith("<shot") and "<camera>" in msg and "CARD: PEOPLE TALKING ON SCREEN" in msg
    assert msg.index("<shot") < msg.index("<camera>") < msg.index("<cards>")
    assert "<scene>" not in msg and "VIDEO ONLY" not in msg
    call = agents.build("shot_prompter").prepare(inp)
    assert call.shared == inp.scene and call.user.startswith("<shot")


def test_video_only_mode_hands_the_stored_opening_and_frame_as_fixed():
    inp = Input.model_validate({**CASES[1]["input"], "mode": "video_only", "fixed": '{"opening": {}, "frame": {}}'})
    msg = agent.user_message(inp)
    assert '<fixed>\n{"opening": {}, "frame": {}}\n</fixed>' in msg and "Return them exactly as given" in msg


def test_a_repair_shows_the_first_answer_and_exactly_the_faults():
    inp = Input.model_validate({**CASES[0]["input"], "repair": ["frame: a still has no motion ('begins to')"],
                                "previous": '{"frame": {}}'})
    msg = agent.user_message(inp)
    assert '<your_first_answer>\n{"frame": {}}' in msg and "- frame: a still has no motion" in msg


def test_every_card_the_step_can_pick_exists():
    for name in agent.CARD_NAMES:
        assert agent.card(name).startswith("CARD:")
    assert agent.card("nothing") == ""


def test_without_a_model_there_is_no_answer_and_no_fallback():
    with pytest.raises(ModelUnavailable):
        agents.build("shot_prompter").run(Input.model_validate(CASES[0]["input"]), RunContext())


def test_the_eval_replies_are_the_labs_five_valid_answers():
    assert len(CASES) == 5
    for case in CASES:
        ShotPrompts.model_validate(case["reply"])


def test_the_prompt_asks_for_a_range_on_every_step_and_keeps_times_out_of_the_text():
    """lab/timecodes (2026-11-21): Google's "[a-bs]" timecodes, from each step's start_s / end_s."""
    text = " ".join(Prompt.load(HERE / "prompts" / "system.md").text.split())
    assert "# Timing (`start_s`, `end_s` on every step)" in text and "a line rarely starts at 0" in text
    assert "said ONLY in its `start_s` and `end_s`" in text
    for case in CASES:
        flow = case["reply"]["video"]["flow"]
        assert flow[0]["start_s"] == 0 and all(s["end_s"] > s["start_s"] for s in flow)
