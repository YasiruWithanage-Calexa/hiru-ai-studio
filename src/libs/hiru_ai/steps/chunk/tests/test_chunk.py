"""Chunking, ported from tests/services/doc_ingest/test_roles_and_chunking.py (plan/2026-11-03 Phase 2).

The input comes the way a system gives it: `extract_text`'s output, found by id and mapped onto `chunk`'s input.
"""
from __future__ import annotations

import base64
from typing import Any

from tests.services.doc_ingest.conftest import CORPUS, make_pdf

from hiru_ai.core import parts
from hiru_ai.steps.chunk import logic as chunking
from hiru_ai.steps.chunk import step


def extracted(data: bytes, filename: str, mime: str) -> dict[str, Any]:
    out = parts.step("extract_text", "step").run(
        {"filename": filename, "mime_type": mime, "data_b64": base64.b64encode(data).decode()})
    assert "rejected" not in out, out
    return {"kind": out["kind"], "lines": out["lines"]}


def chunks(data: bytes, filename: str, mime: str, *, script_like: bool) -> list[dict[str, Any]]:
    return step.run({**extracted(data, filename, mime), "script_like": script_like})["chunks"]


def test_script_chunks_follow_scene_headings():
    out = chunks((CORPUS / "harbour-lights-ep01-script.fountain").read_bytes(), "ep1.fountain", "text/plain",
                 script_like=True)
    scenes = [c for c in out if c["kind"] == "scene"]
    assert [c["heading"] for c in scenes] == [
        "INT. KAMALA'S HOUSE - KITCHEN - DAWN",
        "EXT. KALUGALA HARBOUR - BREAKWATER - MORNING",
        "INT. AUCTION SHED - DAY",
        "EXT. KAMALA'S HOUSE - FRONT YARD - EVENING",
        "EXT. KALUGALA HARBOUR - NIGHT",
        "INT. KAMALA'S HOUSE - BEDROOM - NIGHT",
    ]
    assert "බෝට්ටුව විකුණන්න එපා." in scenes[3]["content"]
    assert [c["ord"] for c in out] == list(range(len(out)))


def test_markdown_chunks_follow_headings():
    out = chunks((CORPUS / "harbour-lights-bible.md").read_bytes(), "bible.md", "text/markdown", script_like=False)
    headings = [c["heading"] for c in out]
    assert "Premise" in headings and "Kamala (කමලා) — the mother" in headings


def test_long_sections_split_under_the_limit_with_overlap():
    paras = [f"Paragraph {i}. " + "The tide comes in and goes out again. " * 12 for i in range(30)]
    out = chunks(("# Long\n\n" + "\n\n".join(paras)).encode(), "long.md", "text/markdown", script_like=False)
    assert len(out) > 3
    assert all(len(c["content"]) <= chunking.MAX_CHARS for c in out)
    assert all(c["heading"] == "Long" for c in out)


def test_one_giant_paragraph_is_still_split():
    out = chunks(("word " * 3000).encode(), "blob.txt", "text/plain", script_like=False)
    assert all(len(c["content"]) <= chunking.MAX_CHARS for c in out)


def test_pdf_chunks_keep_page_ranges():
    pages = [f"INT. ROOM {i} - DAY\nSomeone walks in and sits down at the table by the window." for i in range(3)]
    out = chunks(make_pdf(pages), "s.pdf", "application/pdf", script_like=True)
    assert [(c["page_start"], c["page_end"]) for c in out] == [(1, 1), (2, 2), (3, 3)]


def test_a_chunk_carries_the_hash_retrieval_reuses_embeddings_by():
    out = chunks(b"# One\n\nSome words about the sea that are long enough to keep.", "a.md", "text/markdown",
                 script_like=False)
    assert out[0]["content_hash"] == chunking.Chunk(0, out[0]["heading"], out[0]["content"], None, None,
                                                    "section").content_hash
