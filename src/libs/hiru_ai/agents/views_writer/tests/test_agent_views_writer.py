"""Tests that live with the views_writer agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts import canon
from hiru_ai.agents.views_writer import agent
from hiru_ai.agents.views_writer.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
SYSTEM = Prompt.load(HERE / "prompts" / "system.md").text


def test_the_prompt_is_static_text_with_every_template_slot_in_the_contracts_words():
    assert SYSTEM.strip()
    for name, slots in canon.VIEW_TEMPLATES.items():
        assert f"{name}:\n" + "\n".join(f"  - {s}: {w}" for s, w in slots) in SYSTEM, name


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_lab_answers_pick_the_right_template_and_the_checks_find_what_the_lab_found(case):
    inp, out = Input.model_validate(case["input"]), Output.model_validate(case["reply"])
    written = out.model_dump()
    assert canon.view_template(written["answers"]) == case["lab"]["template"]
    assert [v.slot for v in out.views] == canon.template_slots(case["lab"]["template"])
    assert len(canon.view_findings(written, inp.place.look, inp.scenes)) == case["lab"]["findings"]


def test_the_message_is_the_labs_with_what_comes_and_goes_and_the_re_ask():
    inp = Input.model_validate(CASES[0]["input"])
    text = agent.user_message(inp)
    assert text.startswith("The place: Colombo roadside (a place card).\n\nIts look (the canon card): An urban")
    assert "It has no picture yet: the sheet will be painted from your words only." in text
    assert "Things that come and go here (vehicles with sheets of their own; keep where they stand empty): Family car" \
        in text
    assert "Scenes set there or using it:\nScene 2 — SCENE 02" in text
    again = Input.model_validate({**CASES[0]["input"],
                                  "findings": ["Detail 2 is close on a plain table that no scene uses."],
                                  "picture": {"mime": "image/jpeg", "b64": "AAAA"},
                                  "answers": {"sides": "outside", "moves": False, "size": "long"}})
    text = agent.user_message(again)
    assert "Its picture is attached: keep its look and where its things stand." in text
    assert "The person's answers (use them): sides outside; moves no; size long." in text
    assert text.endswith("without them:\n- Detail 2 is close on a plain table that no scene uses.")
    assert agent.images(again) == [("image/jpeg", "AAAA")] and agent.images(inp) == []
    assert "(a vehicle card)" in agent.user_message(Input.model_validate(CASES[3]["input"]))
