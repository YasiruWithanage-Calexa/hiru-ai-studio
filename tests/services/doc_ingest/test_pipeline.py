from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from doc_ingest.engine import pipeline
from doc_ingest.runtime.config import Config
from doc_ingest.runtime.llm import LLM

from contracts.jobs import DispatchPayload, JobEventType, JobKind, JobStatus
from tests.services.doc_ingest.conftest import CORPUS, FakeOpenAI, make_pdf

CONFIG = Config("http://x", "k", "", "m-medium", "m-low", "low", "minimal", "embed-model", 8)


class FakeStore:
    def __init__(self, data: bytes, filename: str, mime: str, confirmed_role: str | None = None) -> None:
        self.job: dict[str, Any] = {"status": "pending"}
        self.doc: dict[str, Any] | None = {
            "id": "d", "production_id": str(uuid4()), "filename": filename, "mime_type": mime,
            "storage_path": "p/d/file", "confirmed_role": confirmed_role}
        self.data = data
        self.chunks: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []

    def get_job(self, job_id: UUID) -> dict[str, Any] | None:
        return self.job

    def set_job(self, job_id: UUID, status: JobStatus, **fields: Any) -> None:
        self.job = {"status": status.value, **fields}

    def event(self, job_id: UUID, type_: JobEventType, payload: dict[str, Any], agent: str | None = None) -> None:
        self.events.append((type_.value, payload))

    def get_document(self, document_id: UUID) -> dict[str, Any] | None:
        return self.doc

    def update_document(self, document_id: UUID, fields: dict[str, Any]) -> None:
        assert self.doc is not None
        self.doc.update(fields)

    def download(self, bucket: str, path: str) -> bytes:
        return self.data

    def existing_embeddings(self, document_id: UUID) -> dict[str, tuple[list[float], str]]:
        return {r["content_hash"]: (r["embedding"], r["embedding_model"])
                for r in self.chunks if r["embedding"] is not None}

    def replace_chunks(self, document_id: UUID, rows: list[dict[str, Any]]) -> None:
        self.chunks = rows


def _payload() -> DispatchPayload:
    return DispatchPayload(job_id=uuid4(), kind=JobKind.DOC_INGEST, actor_user_id=uuid4(),
                           state={"document_id": str(uuid4())})


def _script_store() -> FakeStore:
    data = (CORPUS / "harbour-lights-ep01-script.fountain").read_bytes()
    return FakeStore(data, "harbour-lights-ep01-script.fountain", "text/plain")


def test_without_a_key_it_indexes_for_keyword_search():
    store = _script_store()
    result = pipeline.run(_payload(), store, LLM(CONFIG))
    assert result["status"] == "ready" and result["embedded"] == 0
    doc = store.doc
    assert doc and doc["status"] == "ready" and doc["detected_role"] == "script"
    assert doc["warnings"] == [pipeline.NO_KEY_WARNING]
    assert doc["chunk_count"] == len(store.chunks) >= 6
    row = store.chunks[1]
    assert row["embedding"] is None and row["corpus"] == "production_docs"
    assert row["context_header"].startswith("harbour-lights-ep01-script.fountain — script — INT.")
    assert store.job["status"] == "done"
    assert store.events[0][0] == "progress"


def test_with_a_key_it_embeds_and_adds_model_headers():
    store = _script_store()
    client = FakeOpenAI()
    usage: list[dict[str, Any]] = []
    result = pipeline.run(_payload(), store, LLM(CONFIG, usage.append, client=client))
    assert result["embedded"] == len(store.chunks)
    assert all(len(r["embedding"]) == 8 and r["embedding_model"] == "embed-model" for r in store.chunks)
    assert all(" — model header " in r["context_header"] for r in store.chunks)
    assert store.doc and store.doc["warnings"] == []
    assert {u["phase"] for u in usage} >= {"doc_ingest.headers", "doc_ingest.embed"}


def test_rerun_reuses_embeddings_instead_of_paying_twice():
    store = _script_store()
    client = FakeOpenAI()
    pipeline.run(_payload(), store, LLM(CONFIG, client=client))
    first = len(client.embed_calls)
    store.job = {"status": "pending"}
    pipeline.run(_payload(), store, LLM(CONFIG, client=client))
    assert len(client.embed_calls) == first  # nothing new to embed


def test_embedding_failure_still_indexes_for_keywords():
    store = _script_store()
    pipeline.run(_payload(), store, LLM(CONFIG, client=FakeOpenAI(fail_embed=True)))
    assert store.doc and store.doc["status"] == "ready"
    assert store.doc["warnings"] == [pipeline.EMBED_FAILED_WARNING]
    assert all(r["embedding"] is None for r in store.chunks)


def test_scanned_pdf_rejects_the_document_and_finishes_the_job():
    store = FakeStore(make_pdf(["", ""]), "scan.pdf", "application/pdf")
    result = pipeline.run(_payload(), store, LLM(CONFIG))
    assert result["status"] == "rejected"
    assert store.doc and store.doc["status"] == "rejected" and "scanned" in store.doc["error"]
    assert store.job["status"] == "done" and store.chunks == []


def test_script_pdf_without_sinhala_warns_about_legacy_fonts():
    garbled = "w;a;h ldfya .sh;="  # how a legacy-font Sinhala line extracts: Latin noise
    pages = [f"INT. HOUSE {i} - DAY\nNIMAL\n{garbled}\nKamala looks out at the sea for a while." for i in range(3)]
    store = FakeStore(make_pdf(pages), "ep2-script.pdf", "application/pdf")
    pipeline.run(_payload(), store, LLM(CONFIG))
    assert store.doc and pipeline.LEGACY_FONT_WARNING in store.doc["warnings"]


def test_confirmed_role_wins_over_detection_for_chunking():
    data = (CORPUS / "director-notes.txt").read_bytes()
    store = FakeStore(data, "notes.txt", "text/plain", confirmed_role="script")
    pipeline.run(_payload(), store, LLM(CONFIG))
    assert store.doc and store.doc["detected_role"] == "notes"  # detection is still recorded


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_finished_job_is_skipped(status):
    store = _script_store()
    store.job = {"status": status}
    assert pipeline.run(_payload(), store, LLM(CONFIG)) == {"skipped": status}
    assert store.chunks == []


def test_deleted_document_finishes_the_job_quietly():
    store = _script_store()
    store.doc = None
    assert pipeline.run(_payload(), store, LLM(CONFIG)) == {"skipped": "document deleted"}
    assert store.job["status"] == "done"
