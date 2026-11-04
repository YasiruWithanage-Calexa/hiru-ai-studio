"""Tests that live with the adam_moment_writer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import Moment, SceneAnalysis, Treatment
from hiru_ai.agents.adam.adam_moment_writer import agent
from hiru_ai.agents.adam.adam_moment_writer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
REPLIES = [c for c in CASES if "reply" in c]


def case(name: str) -> dict[str, Any]:
    return next(c for c in REPLIES if c["name"].startswith(name))


def test_the_prompt_is_static_text_with_one_worked_example():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and text.count("<!-- example:start -->") == 1 and "elaboration" in text


def test_the_user_message_has_the_script_the_analysis_and_the_treatment_with_no_moment_ids_yet():
    message = agent.user_message(Input.model_validate(case("phone_call")["input"]))
    assert message.index("<script>") < message.index("<analysis>") < message.index("<treatment>")
    assert '"plant_moment":""' in message and '"handover"' not in message  # nothing is bound before this agent


def test_every_eval_reply_becomes_moments_and_binds_into_the_plan():
    for c in REPLIES:
        inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
        assert all(isinstance(m, Moment) for m in out.moment_list())
        analysis, treatment = out.bind(inp.analysis, inp.treatment)
        assert isinstance(analysis, SceneAnalysis) and isinstance(treatment, Treatment)
        assert treatment.ending_moment and treatment.ending_moment in {m.id for m in out.moment_list()}, c["name"]


def test_binding_fills_the_ids_the_director_could_only_describe():
    c = case("phone_call")
    inp, out = Input.model_validate(c["input"]), Output.model_validate(c["reply"])
    analysis, treatment = out.bind(inp.analysis, inp.treatment)
    assert treatment.plant and treatment.plant.plant_moment == "m2" and treatment.plant.payoff_moment == "m13"
    assert treatment.rhythm_break and treatment.rhythm_break.moment == "m11" and treatment.ending_moment == "m17"
    assert analysis.pov_owner.handover == "m16"
    assert treatment.plant.plant_when == inp.treatment.plant.plant_when  # the director's words are kept


def test_an_id_that_names_no_moment_is_left_empty_not_guessed():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {**c["reply"], "bindings": {**c["reply"]["bindings"], "plant": "m99", "ending": ""}}
    _, treatment = Output.model_validate(reply).bind(inp.analysis, inp.treatment)
    assert treatment.plant and treatment.plant.plant_moment == "" and treatment.ending_moment == ""


def test_duplicate_or_blank_ids_renumber_the_list_and_clear_the_bindings_rather_than_guess():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {**c["reply"], "moments": [dict(m) for m in c["reply"]["moments"]]}
    reply["moments"][1]["id"] = reply["moments"][0]["id"]
    got = agent.finish(inp, Output.model_validate(reply))
    assert [m.id for m in got.moments] == [f"m{n}" for n in range(1, len(reply["moments"]) + 1)]
    assert got.bindings.plant == got.bindings.ending == ""


def test_spaces_in_an_id_are_removed_and_a_negative_time_is_zero():
    c = case("phone_call")
    inp = Input.model_validate(c["input"])
    reply = {**c["reply"], "moments": [dict(m) for m in c["reply"]["moments"]]}
    reply["moments"][0].update({"id": " m 1 ", "seconds_need": -2.0})
    reply["bindings"] = {**reply["bindings"]}
    got = agent.finish(inp, Output.model_validate(reply))
    assert got.moments[0].id == "m1" and got.moments[0].seconds_need == 0.0
