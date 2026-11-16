"""Tests that live with the breakdown_read agent (ADR 0006): deleting the folder deletes them."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts.breakdown import reading
from hiru_ai.agents.breakdown.breakdown_read import agent
from hiru_ai.agents.breakdown.breakdown_read.schema import Input, Output
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
    msg = reading.numbered("a.pdf", CASES[0]["lines"])
    assert agent.user_message(Input(message=msg)) == msg


def test_the_eval_reply_passes_the_checks_and_asks_for_the_missing_length() -> None:
    case = CASES[0]
    answer = Output.model_validate(case["reply"])
    assert reading.check(answer, case["lines"]) == []
    lines, moved = reading.unglue(case["lines"], answer)
    assert lines[6:8] == ["He returns to work.", "SCENE 02 — ANUDI ARRIVES"]
    assert reading.check(moved, lines) == []
    gates = reading.gates(moved, lines, doc="d", default_s=60)
    assert reading.verdict(gates) == "needs_input"
    assert [q.key for g in gates for q in g.questions] == ["breakdown:length:d:E01-S02"]


def test_a_scripted_call_returns_the_typed_answer() -> None:
    case = CASES[0]
    with use_models(ScriptedChatModel(replies=[case["reply"]])):
        out = build("breakdown_read").run(Input(message=reading.numbered("a.pdf", case["lines"])))
    assert isinstance(out, Output) and len(out.scenes) == 2


def test_no_model_raises_so_the_build_stops() -> None:
    with use_models(ScriptedChatModel(replies=[])), pytest.raises(RuntimeError):
        build("breakdown_read").run(Input(message="x"))
