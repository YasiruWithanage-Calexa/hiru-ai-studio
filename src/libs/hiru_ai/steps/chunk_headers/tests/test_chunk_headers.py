"""The headers are the legacy engine's, unchanged."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from doc_ingest.engine import chunking as old_chunking
from doc_ingest.engine import context as old

from contracts.documents import DocumentRole
from hiru_ai.agents.chunk_contextualiser.agent import ROLE_LABEL as AGENT_ROLE_LABEL
from hiru_ai.steps.chunk_headers import step
from hiru_ai.steps.chunk_headers.logic import ROLE_LABEL

CORPUS = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "corpus"


def test_the_role_labels_are_the_agents_and_the_legacy_ones():
    assert ROLE_LABEL == AGENT_ROLE_LABEL == {r.value: label for r, label in old.ROLE_LABEL.items()}


def test_headers_equal_the_legacy_headers_for_a_whole_script_with_a_partial_model_answer():
    from doc_ingest.engine.extract import extract

    name = "harbour-lights-ep01-script.fountain"
    data = (CORPUS / name).read_bytes()
    chunks = old_chunking.chunk(extract(data, name, "text/plain"), script_like=True)
    answer = {"headers": [{"ord": 1, "header": " Kamala   cooks "}, {"ord": 99, "header": "ghost"},
                          {"ord": 2, "header": ""}]}
    legacy = old.headers(name, DocumentRole.SCRIPT, "full text", chunks, lambda system, user: answer)
    payload = {"filename": name, "role": "script", "chunks": [{**asdict(c)} for c in chunks],
               "answers": [answer["headers"]]}
    got = step.run(payload)["headers"]
    assert {int(k): v for k, v in got.items()} == legacy
    assert got["1"].endswith("Kamala cooks") and "ghost" not in "".join(got.values())


def test_a_failed_batch_keeps_base_headers_and_the_rest_still_count():
    chunks = [{"ord": i, "heading": f"H{i}", "content": "x", "page_start": None, "page_end": None} for i in range(45)]
    out = step.run({"filename": "f", "role": "notes", "chunks": chunks,
                    "answers": [None, [{"ord": 20, "header": "ok"}], None]})
    assert out["batches"] == 3 and out["headers"]["20"].endswith("ok")
    assert out["headers"]["0"] == "f \u2014 notes \u2014 H0"


def test_a_page_range_is_written_as_pp():
    out = step.run({"filename": "f", "role": "script", "chunks": [
        {"ord": 0, "heading": "", "content": "c", "page_start": 2, "page_end": 3},
        {"ord": 1, "heading": "", "content": "c", "page_start": 4, "page_end": 4}]})
    assert out["headers"] == {"0": "f \u2014 script \u2014 pp. 2-3", "1": "f \u2014 script \u2014 p. 4"}
