"""Tests that live with the adam_sound_designer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import ShotCard, SoundMap
from hiru_ai.agents.adam.adam_sound_designer import agent
from hiru_ai.agents.adam.adam_sound_designer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "subjective" in text


def test_the_user_message_has_the_script_the_treatment_the_moments_and_the_cards():
    message = agent.user_message(Input.model_validate(case("phone_call")["input"]))
    assert message.index("<script>") < message.index("<treatment>") < message.index("<moments>") \
        < message.index("<cards>")
    assert '"number":1' in message


def test_every_eval_reply_becomes_a_sound_map_and_gives_every_card_its_sound():
    for c in REPLIES:
        inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
        assert isinstance(out.sound_map(), SoundMap)
        cards = out.apply(inp.cards)
        assert all(isinstance(x, ShotCard) for x in cards) and len(cards) == len(inp.cards), c["name"]


def test_a_good_answer_is_untouched():
    c = case("phone_call")
    inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
    assert agent.finish(inp, out) == out


def test_an_entry_for_a_card_or_a_moment_the_plan_lacks_is_dropped():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    good = c["reply"]
    reply = {**good,
             "subjective": [*good["subjective"], {"moment": "m99", "kind": "drop", "description": "x"}],
             "silences": [*good["silences"], "m98"],
             "pre_laps": [*good["pre_laps"], {"card": 40, "into": "next scene"}],
             "music": [*good["music"], {"moment": "m97", "action": "in"}],
             "cards": [*good["cards"], {"number": 41, "sound": good["cards"][0]["sound"]}]}
    assert agent.finish(inp, Output.model_validate(reply)) == Output.model_validate(good)


def test_a_card_the_designer_did_not_write_for_keeps_the_sound_it_had():
    c = case("phone_call")
    inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
    partial = out.model_copy(update={"cards": out.cards[:1]})
    cards = partial.apply(inp.cards)
    assert cards[0].sound == out.cards[0].sound.card_sound() and cards[1:] == inp.cards[1:]
