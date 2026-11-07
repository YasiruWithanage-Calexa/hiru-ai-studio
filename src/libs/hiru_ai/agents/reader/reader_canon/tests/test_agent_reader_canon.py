"""Tests that live with the reader_canon agent (ADR 0006): deleting the folder deletes them."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from contracts.doc_read import CanonW
from contracts.doc_read_run import canon_message as MESSAGE
from hiru_ai.agents.reader.reader_canon import agent
from hiru_ai.agents.reader.reader_canon.schema import Input, Output
from hiru_ai.core.agents import build
from hiru_ai.core.llm import use_models
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.testing import ScriptedChatModel

HERE = Path(__file__).resolve().parents[1]
ID = "reader_canon"
EMPTY = CanonW(characters=[], locations=[], props=[])
TEXT = Input(filename="e.pdf", role="bible", mode="text", first_page=3, last_page=4, text="L0001 Dinu, 30.",
              pdf_b64="")
PAGES = TEXT.model_copy(update={"mode": "pages", "text": "", "pdf_b64": "JVBERi0xLjQK"})
REPLY = {"canon": EMPTY.model_dump(), "transcription": [{"page": 3, "text": "x"}, {"page": 4, "text": "y"}]}


def test_the_prompt_is_static_text_with_no_document_in_it():
    text = Prompt.load(HERE / "prompts" / "system.md").text
    assert text.strip() and "L0001" not in text and "base64" not in text


def test_there_are_eval_cases():
    cases = yaml.safe_load((HERE / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    assert len(cases) >= 2 and all(c.get("name") for c in cases)


def test_the_message_is_the_one_the_service_sends():
    for inp in (TEXT, PAGES):
        assert agent.user_message(inp) == MESSAGE(inp)


def test_a_pdf_goes_only_in_pages_mode():
    assert agent.files(TEXT) == []
    assert agent.files(PAGES) == [("pages-3-4.pdf", "JVBERi0xLjQK")]


def test_the_pdf_is_sent_as_a_file_part_after_the_text():
    model = ScriptedChatModel(replies=[REPLY])
    with use_models(model):
        out = build(ID).run(PAGES)
    assert isinstance(out, Output)
    content = model.calls[0][-1].content  # what OpenAI receives: tests/hiru_ai/test_reader_files.py
    assert content[0]["type"] == "text" and content[0]["text"] == MESSAGE(PAGES)
    assert content[1]["type"] == "file" and "pages-3-4.pdf" in str(content[1]) and "JVBERi0xLjQK" in str(content[1])


def test_text_mode_sends_text_only():
    model = ScriptedChatModel(replies=[REPLY])
    with use_models(model):
        build(ID).run(TEXT)
    assert isinstance(model.calls[0][-1].content, str)


def test_no_model_raises_so_the_run_keeps_the_rules():
    with use_models(ScriptedChatModel(replies=[])), pytest.raises(RuntimeError):
        build(ID).run(TEXT)
