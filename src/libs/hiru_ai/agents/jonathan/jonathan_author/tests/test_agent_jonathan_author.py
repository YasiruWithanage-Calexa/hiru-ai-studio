"""Tests that live with the jonathan_author agent (ADR 0006): deleting the folder deletes them. That the prompt is the
cinematic lab's to the letter is `tests/jonathan/test_lab_parity.py`."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from contracts.jonathan.scene import SceneS
from hiru_ai.agents.jonathan.jonathan_author import agent
from hiru_ai.agents.jonathan.jonathan_author.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES: list[dict[str, Any]] = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
TEXT = Prompt.load(HERE / "prompts" / "system.md").text


def test_the_prompt_is_static_text_the_team_prompt_then_one_worked_example():
    rules, _example = TEXT.split("# A worked example", 1)
    assert rules.strip() and len(rules.split()) <= 2500 and "4, 6 or 8" in rules
    assert TEXT.count("<example>") == 1 and "Never invent STORY" in rules


def test_the_worked_example_is_a_valid_answer_of_another_scene():
    shown = TEXT.split("Your answer:\n", 1)[1].split("\n</example>", 1)[0]
    plan = Output.model_validate_json(shown)
    assert plan.treatment.logline and len(plan.sequences) >= 2 and len(plan.shots) >= 6
    assert any(s.use_s < s.take_s for s in plan.shots) and plan.treatment.advice  # what the lab's example shows
    assert "The Envelope" in TEXT


def test_the_rules_name_no_person_or_object_of_one_story():
    rules = TEXT.split("# A worked example", 1)[0]
    # the lab's test: the names and the objects of its own scenes (a phone in general is craft, not a story)
    for word in ("Kasun", "Anudi", "Dasun", "puddle", "umbrella", "tea", "rain", "envelope", "three-wheeler"):
        assert not re.search(rf"\b{word}\b", rules, re.IGNORECASE), word


def test_the_user_message_is_the_context_pack_as_it_stands():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.user_message(inp) == inp.pack and "<script>" in inp.pack and "who they are:" in inp.pack


def test_a_reference_the_scene_lacks_is_cleaned_entry_by_entry_and_nothing_else_is_judged():
    case = next(c for c in CASES if c["name"].startswith("stray"))
    out = agent.finish(Input.model_validate(case["input"]), Output.model_validate(case["reply"]))
    assert out.shots[1].blocks == [1] and out.shots[1].lines == ["L1"]
    assert [m.who for m in out.staging.marks] == ["Anudi"]  # a stranger's mark and a mark at a block the scene lacks go
    assert out.treatment == Output.model_validate(case["reply"]).treatment


def test_the_schema_the_model_is_held_to_carries_the_clip_schema():
    schema = agent.output_schema()
    assert "ir" in schema["properties"]["shots"]["items"]["properties"] and "$ref" not in str(schema)
    assert list(schema["properties"])[:2] == ["treatment", "sequences"]


def test_the_manifest_asks_for_the_timeout_an_answer_of_this_size_needs_and_the_jonathan_tier():
    from hiru_ai.core import agents

    built = agents.build("jonathan_author")
    assert built.manifest.timeout_s == 900 and built.manifest.model == "jonathan"


def test_the_scene_in_the_case_is_a_scene():
    assert SceneS.model_validate(CASES[0]["input"]["scene"]).lines
