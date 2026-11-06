"""Tests that live with the david_author agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hiru_ai.agents.david.david_author import agent
from hiru_ai.agents.david.david_author.schema import Input, Output
from hiru_ai.core.prompts import Prompt

HERE = Path(__file__).resolve().parents[1]
CASES: list[dict[str, Any]] = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and len(text.split()) <= 2500


def test_the_prompt_holds_one_worked_example_that_is_a_valid_answer():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.count("<!-- example:start -->") == 1 and "4, 6 or 8" in text
    shown = text.split("Your answer:\n", 1)[1].split("\n</example>", 1)[0]
    assert len(Output.model_validate_json(shown).shots) == 6


def test_the_user_message_is_the_context_pack_as_it_stands():
    inp = Input.model_validate(CASES[0]["input"])
    assert agent.user_message(inp) == inp.pack and "<script>" in inp.pack


def test_a_reference_the_scene_lacks_is_cleaned_entry_by_entry_and_nothing_else_is_judged():
    case = next(c for c in CASES if c["name"].startswith("stray"))
    out = agent.finish(Input.model_validate(case["input"]), Output.model_validate(case["reply"]))
    assert out.shots[1].blocks == [1] and out.shots[1].lines == ["L1"]
    assert [m.who for m in out.staging.marks] == ["Anudi"]


def test_the_schema_the_model_is_held_to_carries_the_clip_schema():
    schema = agent.output_schema()
    assert "ir" in schema["properties"]["shots"]["items"]["properties"] and "$ref" not in str(schema)


def test_the_manifest_asks_for_the_timeout_an_answer_of_this_size_needs_and_the_author_tier():
    from hiru_ai.core import agents

    built = agents.build("david_author")
    assert built.manifest.timeout_s == 600 and built.manifest.model == "author"
