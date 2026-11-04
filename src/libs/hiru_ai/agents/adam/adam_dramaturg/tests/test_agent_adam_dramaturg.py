"""Tests that live with the adam_dramaturg agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import SceneAnalysis
from hiru_ai.agents.adam.adam_dramaturg import agent
from hiru_ai.agents.adam.adam_dramaturg.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "<example>" in text


def test_the_user_message_carries_the_scene_with_its_block_numbers_and_line_ids():
    message = agent.user_message(Input.model_validate(case("phone_call")["input"]))
    assert "<script>" in message and "b4 line [L4]" in message and "Present: Anudi, Dasun" in message
    assert "<grammar>" not in message  # none given


def test_grammar_and_context_go_in_the_user_message_never_the_prompt():
    inp = Input.model_validate({**case("phone_call")["input"], "grammar": "Murch: emotion first",
                                "context": {"heading": "The Phone Call", "note": "keep it quiet"}})
    message = agent.user_message(inp)
    assert "<grammar>\nMurch: emotion first" in message and "Director's note: keep it quiet" in message


def test_every_eval_reply_is_a_valid_output_that_becomes_an_analysis():
    for c in REPLIES:
        assert isinstance(Output.model_validate(c["reply"]).analysis(), SceneAnalysis), c["name"]


def test_a_reference_to_a_block_the_scene_does_not_have_is_dropped_not_repaired():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {**c["reply"], "beats": [*c["reply"]["beats"], {"blocks": [77], "action": "x", "reaction": "y",
                                                           "turn": False, "reactor": ""}],
             "subtext": [{"block": 99, "who": "Anudi", "behaviour": "x", "object": "", "sound": ""}],
             "audience_knows": [{"fact": "f", "who_doesnt": "Dasun", "from_block": 42}]}
    cleaned, dropped = agent.clean(inp.scene, Output.model_validate(reply))
    assert len(cleaned.beats) == len(c["reply"]["beats"]) and cleaned.subtext == [] and cleaned.audience_knows == []
    assert len(dropped) == 3  # the beat's block (the beat goes with it), the subtext, the knowledge
    assert cleaned.key_moment == Output.model_validate(c["reply"]).key_moment  # a good key moment is untouched


def test_a_key_moment_on_a_missing_block_moves_to_the_break_then_to_the_last_block():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    lost = {**c["reply"], "key_moment": {"block": 50, "why": "x"}}
    moved, notes = agent.clean(inp.scene, Output.model_validate(lost))
    assert moved.key_moment.block == c["reply"]["break_block"] and "moved to block" in notes[0]
    none = {**lost, "break_block": None}
    assert agent.clean(inp.scene, Output.model_validate(none))[0].key_moment.block == 9  # the last block


def test_finish_is_the_clean_answer():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    assert agent.finish(inp, Output.model_validate(c["reply"])) == Output.model_validate(c["reply"])


def test_a_want_with_no_person_or_verb_is_dropped():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    extra = [{"who": " ", "verb": "to hide"}, {"who": "Dasun", "verb": ""}]
    reply = {**c["reply"], "wants": [*c["reply"]["wants"], *extra]}
    assert agent.finish(inp, Output.model_validate(reply)).wants == Output.model_validate(c["reply"]).wants
