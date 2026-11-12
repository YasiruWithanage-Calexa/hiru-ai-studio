"""Tests that live with the breakdown_series agent (ADR 0006): deleting the folder deletes them."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hiru_ai.agents.breakdown.breakdown_series import agent
from hiru_ai.agents.breakdown.breakdown_series.schema import Input, Output
from hiru_ai.core.agents import build
from hiru_ai.core.llm import use_models
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.testing import ScriptedChatModel

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_with_no_document_in_it() -> None:
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and "<document filename" not in text and "Ekama" not in text


def test_the_prompt_keeps_runtime_and_direction_out() -> None:
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert "running time" in text and "left_out" in text and "HOW to shoot" in text


def test_the_message_is_the_one_the_run_built() -> None:
    assert agent.user_message(Input(message="<document>x</document>")) == "<document>x</document>"


def test_the_eval_replies_are_valid_answers() -> None:
    for case in CASES:
        Output.model_validate(case["reply"])


def test_a_scripted_call_returns_the_typed_answer() -> None:
    case = CASES[0]
    with use_models(ScriptedChatModel(replies=[case["reply"]])):
        out = build("breakdown_series").run(Input.model_validate(case["input"]))
    assert isinstance(out, Output)
    assert [f.name.casefold() for f in out.genre.facets if f.weight == "main"] == ["action", "crime thriller"]


def test_no_model_raises_so_the_run_stays_absent_safe() -> None:
    with use_models(ScriptedChatModel(replies=[])), pytest.raises(RuntimeError):
        build("breakdown_series").run(Input(message="x"))
