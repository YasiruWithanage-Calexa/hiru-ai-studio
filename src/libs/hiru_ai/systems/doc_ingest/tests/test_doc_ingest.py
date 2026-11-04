"""The doc_ingest system's own behaviour on the core fakes (the whole-service fixtures are tests/parity)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from doc_ingest.engine import pipeline as legacy

from contracts.documents import DocumentRole
from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core import llm
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeDocs, FakeFiles, FakeJobs
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.doc_ingest import graph, rules

CORPUS = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "corpus"
SCRIPT = "harbour-lights-ep01-script.fountain"


def setup(filename: str = SCRIPT, *,
          confirmed: str | None = None) -> tuple[FakeDocs, FakeFiles, FakeJobs, DispatchPayload]:
    document_id, production_id = uuid4(), uuid4()
    docs = FakeDocs([{"id": str(document_id), "production_id": str(production_id), "filename": filename,
                      "mime_type": "text/plain", "storage_path": "p/f", "confirmed_role": confirmed}])
    files = FakeFiles({("documents", "p/f"): (CORPUS / SCRIPT).read_bytes()})
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.DOC_INGEST, actor_user_id=uuid4(),
                              state={"document_id": str(document_id)})
    return docs, files, FakeJobs(), payload


def ctx_of(docs: FakeDocs, files: FakeFiles, jobs: FakeJobs) -> RunContext:
    return RunContext(ports=replace(Ports(), docs=docs, files=files, jobs=jobs))


def test_the_text_keeps_page_breaks_and_the_hashes_are_the_legacy_ones():
    lines = [{"text": "a", "page": 1}, {"text": "b", "page": 1}, {"text": "c", "page": 2}]
    assert rules.paged_text(lines) == "a\nb\fc"
    assert rules.embed_hash("m", "t") == legacy.embed_hash("m", "t")
    assert rules.LEGACY_FONT_WARNING == legacy.LEGACY_FONT_WARNING and rules.NO_KEY_WARNING == legacy.NO_KEY_WARNING


def test_a_script_pdf_without_sinhala_is_warned_about_and_other_documents_are_not():
    pdf = {"kind": "pdf", "has_sinhala": False}
    assert rules.legacy_font_warning(pdf, "script") == rules.LEGACY_FONT_WARNING
    assert rules.legacy_font_warning(pdf, "notes") is None
    assert rules.legacy_font_warning({"kind": "text", "has_sinhala": False}, "script") is None
    assert legacy.legacy_font_warning.__name__  # the legacy function it was ported from


def test_a_finished_delivery_is_skipped_and_touches_nothing():
    docs, files, jobs, payload = setup()
    jobs.status = "done"
    assert graph.run(payload, ctx_of(docs, files, jobs)) == {"skipped": "done"}
    assert docs.document_rows[0].get("status") is None and not getattr(docs, "chunk_rows", [])


def test_a_document_deleted_while_queued_finishes_the_job():
    docs, files, jobs, payload = setup()
    docs.document_rows.clear()
    assert graph.run(payload, ctx_of(docs, files, jobs)) == {"skipped": "document deleted"}
    assert jobs.status == "done" and jobs.fields["result"] == {"skipped": "document deleted"}


def test_without_a_key_it_indexes_for_keywords_and_says_so():
    docs, files, jobs, payload = setup()
    result = graph.run(payload, ctx_of(docs, files, jobs))
    row = docs.document_rows[0]
    assert result["status"] == "ready" and result["embedded"] == 0 and row["warnings"] == [rules.NO_KEY_WARNING]
    assert row["chunk_count"] == len(docs.chunk_rows) and all(c["embedding"] is None for c in docs.chunk_rows)
    assert jobs.status == "done" and files.objects[("documents", row["text_path"])].decode("utf-8")


def test_a_confirmed_role_wins_over_the_guess_for_chunking_but_the_guess_is_still_recorded():
    docs, files, jobs, payload = setup(confirmed="notes")
    graph.run(payload, ctx_of(docs, files, jobs))
    row = docs.document_rows[0]
    assert row["detected_role"] == "script" and DocumentRole(row["detected_role"]) is DocumentRole.SCRIPT
    assert all(c["context_header"].split(" — ")[1] == "notes" for c in docs.chunk_rows)


def test_a_model_that_fails_leaves_the_rules_role_and_base_headers():
    docs, files, jobs, payload = setup("unclear.txt")
    files.objects[("documents", "p/f")] = b"Some words without a screenplay's shape. " * 40
    with llm.use_models(RoutedChatModel(routes={})):  # a model that answers nothing: every call raises
        graph.run(payload, ctx_of(docs, files, jobs))
    row = docs.document_rows[0]
    assert row["status"] == "ready" and row["role_reason"].endswith("(rules)")
    assert all(" — " in c["context_header"] for c in docs.chunk_rows)


def test_a_rejected_file_is_a_finished_job_with_no_chunks():
    docs, files, jobs, payload = setup()
    files.objects[("documents", "p/f")] = b"\xff\xfe\x00bad"
    docs.document_rows[0]["mime_type"] = "application/pdf"
    out: dict[str, Any] = graph.run(payload, ctx_of(docs, files, jobs))
    assert out["status"] == "rejected" and docs.document_rows[0]["status"] == "rejected"
    assert jobs.status == "done" and not docs.chunk_rows
