"""Tests that live with the adam_blocker agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import Staging
from hiru_ai.agents.adam.adam_blocker import agent
from hiru_ai.agents.adam.adam_blocker.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "teleport" in text


def test_the_origin_of_the_copied_prompt_is_recorded():
    origin = (HERE / "ORIGIN.md").read_text(encoding="utf-8")
    assert "agents/stager" in origin and "Commit" in origin and "Changes" in origin


def test_the_user_message_lists_the_place_the_treatment_and_one_row_a_moment():
    message = agent.user_message(Input.model_validate(case("phone_call")["input"]))
    assert "A bench by the lake" in message and "Objects: bench, lake, phone" in message
    assert "m7 [script] who: Anudi, Dasun | Anudi sees who it is" in message and "objects: phone" in message


def test_every_eval_reply_becomes_a_staging():
    for c in REPLIES:
        assert isinstance(Output.model_validate(c["reply"]).staging(), Staging), c["name"]


def test_a_good_answer_is_untouched():
    c = case("phone_call")
    inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
    assert agent.finish(inp, out) == out


def test_a_mark_or_move_for_a_moment_or_a_person_the_scene_lacks_is_dropped():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    out = Output.model_validate({
        "marks": [*c["reply"]["marks"],
                  {"moment": "m99", "who": "Anudi", "zone": "path", "facing": "", "holding": []},
                  {"moment": "m1", "who": "Anudi's mother", "zone": "path", "facing": "", "holding": []}],
        "moves": [*c["reply"]["moves"],
                  {"moment": "m1", "who": "A stranger", "from_zone": "a", "to_zone": "b", "why": "enter"}]})
    got = agent.finish(inp, out)
    assert got == Output.model_validate(c["reply"])
