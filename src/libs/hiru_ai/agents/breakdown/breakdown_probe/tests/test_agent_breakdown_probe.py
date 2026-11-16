"""Tests that live with the breakdown_probe agent (ADR 0006): deleting the folder deletes them."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts.breakdown import reading
from hiru_ai.agents.breakdown.breakdown_probe import agent
from hiru_ai.agents.breakdown.breakdown_probe.schema import Input, Output
from hiru_ai.core.agents import build
from hiru_ai.core.llm import use_models
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.testing import ScriptedChatModel

HERE = Path(__file__).resolve().parents[1]
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_with_no_document_in_it() -> None:
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and "L0001 | SCENE" not in text


def test_the_message_is_the_one_the_reading_built() -> None:
    msg = reading.numbered("a.pdf", ["SCENE 01", "Kasun smiles."])
    assert agent.user_message(Input(message=msg)) == msg


def test_the_eval_replies_are_valid_answers_and_gate_as_expected() -> None:
    levels = [reading.verdict(reading.probe_gates(Output.model_validate(c["reply"]))) for c in CASES]
    assert levels == ["go", "stop", "stop"]


def test_a_scripted_call_returns_the_typed_answer() -> None:
    case = CASES[0]
    with use_models(ScriptedChatModel(replies=[case["reply"]])):
        out = build("breakdown_probe").run(Input.model_validate(case["input"]))
    assert isinstance(out, Output) and out.text_quality.readable


def test_no_model_raises_so_the_build_stops() -> None:
    with use_models(ScriptedChatModel(replies=[])), pytest.raises(RuntimeError):
        build("breakdown_probe").run(Input(message="x"))
