"""Tests that live with the adam_shot_designer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import ShotCard
from hiru_ai.agents.adam.adam_shot_designer import agent
from hiru_ai.agents.adam.adam_shot_designer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "4, 6 or 8" in text


def test_the_user_message_carries_the_clock_the_designer_groups_moments_on():
    inp = Input.model_validate(case("phone_call")["input"])
    message = agent.user_message(inp)
    assert message.index("<script>") < message.index("<treatment>") < message.index("<moments>") \
        < message.index("<staging>") < message.index("<clock>")
    clock = message[message.index("<clock>"):]
    assert "line L4: " in clock and "words" in clock and "m9: " in clock and "s on the clock" in clock
    assert "after the last word" in clock


def test_a_moment_with_a_line_is_counted_by_its_speech_plus_the_lead_in():
    inp = Input.model_validate(case("phone_call")["input"])
    rows = dict(r.split(": ", 1) for r in agent.clock_text(inp.scene, inp.moments).splitlines() if ": " in r)
    short = next(m for m in inp.moments if m.id == "m12")  # a one-line moment: longer than its 2.5 s?
    seconds = float(rows["m12"].split(" s on the clock")[0])
    assert seconds >= short.seconds_need + 0.5 - 1e-9  # the lead-in before a first word is always added


def test_every_eval_reply_becomes_numbered_cards():
    for c in REPLIES:
        cards = Output.model_validate(c["reply"]).card_list()
        assert [x.number for x in cards] == list(range(1, len(cards) + 1)), c["name"]
        assert all(isinstance(x, ShotCard) and x.take_s in (4, 6, 8) for x in cards)


def test_the_designer_can_name_only_the_takes_veo_makes():
    reply = {"cards": [dict(case("phone_call")["reply"]["cards"][0], take_s=5)]}
    try:
        Output.model_validate(reply)
    except ValueError as exc:
        assert "take_s" in str(exc)
    else:
        raise AssertionError("a 5 s take was accepted")


def test_a_card_that_shows_no_moment_is_dropped():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {"cards": [*c["reply"]["cards"], {**c["reply"]["cards"][0], "moments": []}]}
    assert len(agent.finish(inp, Output.model_validate(reply)).cards) == len(c["reply"]["cards"])
