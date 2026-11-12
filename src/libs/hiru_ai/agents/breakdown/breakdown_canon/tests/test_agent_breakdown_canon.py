"""Tests that live with the breakdown_canon agent (ADR 0006): deleting the folder deletes them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from contracts import canon_refine as cr
from contracts.safe_depiction import PROMPT_LINE
from hiru_ai.agents.breakdown.breakdown_canon import agent
from hiru_ai.agents.breakdown.breakdown_canon.schema import Input, Output
from hiru_ai.core.agents import build
from hiru_ai.core.llm import use_models
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.testing import ScriptedChatModel

HERE = Path(__file__).resolve().parents[1]
FIX = HERE.parents[5] / "tests" / "fixtures" / "canon_refine"
CASES = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))


def test_the_prompt_is_static_text_with_no_document_in_it() -> None:
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and "Ekama" not in text and "THE DOCUMENTS" not in text


def test_the_prompt_carries_the_safe_depiction_line() -> None:
    assert " ".join(PROMPT_LINE.split()) in " ".join(Prompt.load(HERE / "prompts" / "system.md").text.split())


def test_the_prompt_keeps_ids_out_of_descriptions_and_reasons_out_of_values() -> None:
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert "never an id such as C01" in text and 'no "suggests"' in text and "`spot`" in text


def test_the_message_is_the_one_contracts_builds() -> None:
    from contracts.breakdown.schema import Breakdown

    fx = json.loads((FIX / "ekama.json").read_text(encoding="utf-8"))
    msg = cr.message(Breakdown.model_validate(fx["memory"]), fx["lines"], fx["canon"])
    assert CASES[0]["input"]["message"].rstrip("\n") == msg.rstrip("\n")


def test_the_message_is_the_one_the_job_built() -> None:
    assert agent.user_message(Input(message="THE PRODUCTION")) == "THE PRODUCTION"


def test_the_eval_reply_is_a_valid_answer_that_passes_the_checks() -> None:
    from contracts.breakdown.schema import Breakdown

    fx = json.loads((FIX / "ekama.json").read_text(encoding="utf-8"))
    out = Output.model_validate(CASES[0]["reply"])
    assert cr.check(out, Breakdown.model_validate(fx["memory"]), fx["lines"]) == []


def test_a_scripted_call_returns_the_typed_answer() -> None:
    case = CASES[0]
    with use_models(ScriptedChatModel(replies=[case["reply"]])):
        out = build("breakdown_canon").run(Input.model_validate(case["input"]))
    assert isinstance(out, Output)


def test_no_model_raises_so_the_job_keeps_the_canon_as_it_is() -> None:
    with use_models(ScriptedChatModel(replies=[])), pytest.raises(RuntimeError):
        build("breakdown_canon").run(Input(message="x"))
