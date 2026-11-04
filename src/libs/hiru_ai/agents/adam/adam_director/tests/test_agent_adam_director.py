"""Tests that live with the adam_director agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import Treatment
from hiru_ai.agents.adam.adam_director import agent
from hiru_ai.agents.adam.adam_director.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "restrained" in text


def test_the_user_message_has_the_script_then_the_analysis_and_optional_neighbours():
    inp = Input.model_validate({**case("phone_call")["input"], "before": "A kitchen at noon", "devices": "pillow shot"})
    message = agent.user_message(inp)
    assert message.index("<devices>") < message.index("<neighbours>") < message.index("<script>") \
        < message.index("<analysis>")
    assert "The scene before: A kitchen at noon" in message and '"break":{"block":4}' in message
    assert "<neighbours>" not in agent.user_message(Input.model_validate(case("phone_call")["input"]))


def test_every_eval_reply_is_three_treatments_one_for_each_stance_in_order():
    for c in REPLIES:
        out = Output.model_validate(c["reply"])
        assert [t.stance for t in out.treatments] == ["restrained", "intimate", "heightened"], c["name"]
        assert all(isinstance(t, Treatment) for t in out.all())


def test_a_duplicate_stance_is_dropped_and_the_order_is_restored():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    t = c["reply"]["treatments"]
    out = Output.model_validate({"treatments": [t[2], t[0], t[0], t[1]]})
    got = agent.finish(inp, out)
    assert [x.stance for x in got.treatments] == ["restrained", "intimate", "heightened"]


def test_a_section_naming_a_beat_the_analysis_lacks_loses_that_beat():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {"treatments": [dict(t) for t in c["reply"]["treatments"]]}
    reply["treatments"][0]["sections"] = [{**reply["treatments"][0]["sections"][0], "beats": [0, 9]}]
    got = agent.finish(inp, Output.model_validate(reply))
    assert got.treatments[0].sections[0].beats == [0]


def test_a_plant_of_an_object_the_place_does_not_have_is_dropped():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {"treatments": [dict(t) for t in c["reply"]["treatments"]]}
    reply["treatments"][1]["plant"] = {**reply["treatments"][1]["plant"], "object": "a pistol"}
    got = agent.finish(inp, Output.model_validate(reply))
    assert got.treatments[1].plant is None and got.treatments[0].plant is not None
