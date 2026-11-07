"""The document reader in the doc_ingest function (plan/2026-11-06f §4.5): off by default; on, it reads a script once,
keeps the reading beside the text and, for a scrambled PDF, chunks the clean transcription instead."""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from doc_ingest.engine import pipeline
from doc_ingest.runtime.llm import LLM

from contracts.doc_read import Reading
from contracts.doc_read_quality import Quality
from tests.contracts.reader_fakes import canon_answer, piece_answer
from tests.services.doc_ingest.conftest import CORPUS, FakeOpenAI, make_pdf
from tests.services.doc_ingest.test_pipeline import CONFIG, FakeStore, _payload

ON = replace(CONFIG, openai_api_key="k", reader_enabled=True)


class ReaderOpenAI(FakeOpenAI):
    """Answers the reader's calls from the message it is sent; everything else as FakeOpenAI does."""

    def _chat(self, **kwargs: Any) -> Any:
        name = kwargs["response_format"]["json_schema"]["name"]
        if name not in ("PieceRead", "CanonRead"):
            return super()._chat(**kwargs)
        self.chat_calls.append(kwargs)
        content = kwargs["messages"][1]["content"]
        text = content if isinstance(content, str) else content[0]["text"]
        body = piece_answer(text) if name == "PieceRead" else canon_answer(text)
        from types import SimpleNamespace

        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                prompt_tokens_details=SimpleNamespace(cached_tokens=0))
        return SimpleNamespace(usage=usage, choices=[SimpleNamespace(finish_reason="stop",
                                                                     message=SimpleNamespace(content=json.dumps(body)))])


def script_store() -> FakeStore:
    data = (CORPUS / "harbour-lights-ep01-script.fountain").read_bytes()
    return FakeStore(data, "harbour-lights-ep01-script.fountain", "text/plain", confirmed_role="script")


def reader_calls(client: FakeOpenAI) -> list[dict[str, Any]]:
    return [c for c in client.chat_calls if c["response_format"]["json_schema"]["name"] in ("PieceRead", "CanonRead")]


def test_off_by_default_nothing_is_read():
    store, client = script_store(), ReaderOpenAI()
    pipeline.run(_payload(), store, LLM(replace(CONFIG, openai_api_key="k"), client=client))
    assert reader_calls(client) == []
    assert store.doc is not None and "reading_path" not in store.doc


def test_a_clean_script_is_read_from_its_text_and_kept_beside_it():
    store, client = script_store(), ReaderOpenAI()
    result = pipeline.run(_payload(), store, LLM(ON, client=client))
    assert result["status"] == "ready"
    calls = reader_calls(client)
    assert len(calls) == 1 and calls[0]["model"] == "gpt-5" and calls[0]["reasoning_effort"] == "medium"
    assert calls[0]["timeout"] == 900.0 and isinstance(calls[0]["messages"][1]["content"], str)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert store.doc is not None and store.doc["read_from"] == "text"
    reading = Reading.loads(store.texts[store.doc["reading_path"]])
    assert reading is not None and reading.source == "text" and reading.episodes[0].scenes
    assert store.doc["reading_path"].endswith("/reading.json")


def test_a_reader_that_fails_leaves_the_rules_and_says_why():
    class Broken(ReaderOpenAI):
        def _chat(self, **kwargs: Any) -> Any:
            if kwargs["response_format"]["json_schema"]["name"] == "PieceRead":
                raise RuntimeError("down")
            return super()._chat(**kwargs)

    store = script_store()
    result = pipeline.run(_payload(), store, LLM(ON, client=Broken()))
    assert result["status"] == "ready"
    assert store.doc is not None and store.doc["reading_path"] is None and store.doc["read_from"] is None
    assert any("the rules read it instead" in e[1].get("text", "") for e in store.events)


def test_a_scrambled_pdf_is_read_from_its_pages_and_its_transcription_is_chunked(monkeypatch: pytest.MonkeyPatch):
    pages = [f"SCRAMBLED {n} " + "words on the page that a font scrambled " * 3 for n in ("ONE", "TWO", "THREE")]
    store = FakeStore(make_pdf(pages), "avasana.pdf", "application/pdf", confirmed_role="script")
    scrambled = Quality([])
    monkeypatch.setattr(type(scrambled), "mode", property(lambda self: "pages"))
    client = ReaderOpenAI()
    result = pipeline.run(_payload(), store, LLM(ON, client=client))
    assert result["status"] == "ready"
    call = reader_calls(client)[0]
    content = call["messages"][1]["content"]
    assert content[1]["type"] == "file" and content[1]["file"]["filename"] == "pages-1-3.pdf"
    assert content[1]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert store.doc is not None and store.doc["read_from"] == "pages"
    text = " ".join(c["content"] for c in store.chunks)
    assert "clean page 1" in text and "SCRAMBLED" not in text  # decision 8: search reads the transcription
    assert "SCRAMBLED ONE" in store.texts[next(p for p in store.texts if p.endswith("extracted.txt"))]  # kept
