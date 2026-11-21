"""Tests that live with the camera_agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
import yaml

from contracts import camera as cam
from hiru_ai.agents.camera_agent import agent, schema
from hiru_ai.agents.camera_agent.schema import ClipCamera, Input, Move, SceneCamera, Size
from hiru_ai.core import agents
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_carries_the_measured_rules_and_the_two_issues():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    # plan/2026-11-20d §6: lab/camera_moves' prompt, cinematic by logic
    assert "MOMENT" in text and "INTENSITY 1-5" in text and "POWER" in text
    flat = " ".join(text.split())
    assert "IGNORES a float" in flat  # measured 2026-11-20
    assert "NEVER name gear" in flat and "At most 220 characters" in flat
    assert "Angle and height carry power" in flat and "at most two clips in three" in flat
    assert '"The camera" is always' in flat  # §6.3
    assert "PRODUCTION'S OWN DIRECTION" in text
    assert "One clip at a time" in text  # D3: the Ask and a chat turn's clip


def test_the_schema_speaks_the_catalogue():
    """D6: every Literal is `contracts.camera`'s list, in its order, so the schema, the checks and the panel agree."""
    lists = {"Support": cam.SUPPORTS, "Move": cam.MOVE_SLUGS, "Speed": cam.SPEEDS, "Size": cam.SIZES,
             "Angle": cam.ANGLES, "Height": cam.HEIGHTS, "Lens": cam.LENSES, "Aperture": cam.APERTURES,
             "Focus": cam.FOCUS, "Composition": cam.COMPOSITIONS, "Time": cam.TIMES, "Axis": cam.AXES}
    for name, values in lists.items():
        assert get_args(getattr(schema, name)) == tuple(values), name
    assert len(get_args(Move)) == 51 and {"MWS", "MLS", "ECU", "EWS"} <= set(get_args(Size))


def test_the_scene_goes_first_as_its_own_message_then_the_clips():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.shared_message(inp) == inp.scene
    msg = agent.user_message(inp)
    assert msg.startswith("<clips>") and "<scene>" not in msg and "scene_camera" not in msg
    call = agents.build("camera_agent").prepare(inp)
    assert call.shared == inp.scene and call.user.startswith("<clips>")


def test_an_ask_names_the_one_clip_the_note_and_the_scene_camera():
    ask = next(c for c in CASES if c["input"].get("focus"))
    msg = agent.user_message(Input.model_validate(ask["input"]))
    assert "<scene_camera>" in msg and "clip 4C-1 only" in msg and "visible slow push" in msg
    assert "Answer `clips` with that one clip" in msg


def test_a_repair_shows_the_first_answer_and_exactly_the_faults():
    inp = Input.model_validate({**CASES[0]["input"], "repair": ["4B-1: the camera sentence names gear ('dolly')"],
                                "previous": '{"clips": []}'})
    msg = agent.user_message(inp)
    assert '<your_first_answer>\n{"clips": []}' in msg and "- 4B-1: the camera sentence names gear" in msg
    assert "(every clip)" in msg


def test_without_a_model_there_is_no_answer_and_no_fallback():
    with pytest.raises(ModelUnavailable):
        agents.build("camera_agent").run(Input.model_validate(CASES[0]["input"]), RunContext())


def test_the_eval_replies_are_valid_answers_of_one_clip_each():
    assert len(CASES) >= 5
    moves = set()
    for case in CASES:
        answer = SceneCamera.model_validate(case["reply"])
        assert len(answer.clips) == 1
        moves.add(answer.clips[0].move)
    assert {"follow_pan", "push_then_hold", "hold", "pull_out", "push_in", "crane_up"} <= moves
    for case in CASES:  # §6: every reply names the moment, its intensity and who holds the power
        c = case["reply"]["clips"][0]
        assert c["moment"] and 1 <= c["intensity"] <= 5 and c["power"] and case["reply"]["peak_slate"]
    ClipCamera.model_validate(CASES[0]["reply"]["clips"][0])
