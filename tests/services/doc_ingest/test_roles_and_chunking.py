from __future__ import annotations

import pytest
from doc_ingest.engine import chunking, roles
from doc_ingest.engine.extract import extract

from contracts.documents import DocumentRole
from tests.services.doc_ingest.conftest import CORPUS, make_pdf


def _text(name: str) -> str:
    return (CORPUS / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("name", "role"), [
    ("harbour-lights-ep01-script.fountain", DocumentRole.SCRIPT),
    ("harbour-lights-bible.md", DocumentRole.BIBLE),
    ("harbour-lights-canon-index.md", DocumentRole.CANON_INDEX),
    ("harbour-lights-outline.txt", DocumentRole.OUTLINE),
    ("director-notes.txt", DocumentRole.NOTES),
])
def test_rules_recognise_the_fixture_corpus(name, role):
    assert roles.detect_by_rules(name, _text(name)).role == role


def test_script_by_content_alone_is_confident():
    guess = roles.detect_by_rules("untitled.txt", _text("harbour-lights-ep01-script.fountain"))
    assert guess.role == DocumentRole.SCRIPT and guess.confidence >= 0.8


def test_unsure_rules_ask_the_model():
    calls = []

    def ask(system, user):
        calls.append(user)
        return {"role": "notes", "confidence": 0.9, "reason": "director's notes"}

    guess = roles.detect("untitled.txt", "Some loose thoughts about the shoot.", ask)
    assert guess.role == DocumentRole.NOTES and guess.source == "model" and calls


def test_confident_rules_do_not_call_the_model():
    def ask(system, user):
        raise AssertionError("model should not be called")

    roles.detect("x.fountain", _text("harbour-lights-ep01-script.fountain"), ask)


def test_model_failure_keeps_the_rules_answer():
    def ask(system, user):
        raise RuntimeError("timeout")

    assert roles.detect("untitled.txt", "loose thoughts", ask).source == "rules"


def test_model_cannot_claim_certainty():
    guess = roles.detect("u.txt", "text", lambda s, u: {"role": "bible", "confidence": 7, "reason": ""})
    assert guess.confidence <= 0.95


def test_script_chunks_follow_scene_headings():
    ex = extract((CORPUS / "harbour-lights-ep01-script.fountain").read_bytes(), "ep1.fountain", "text/plain")
    chunks = chunking.chunk(ex, script_like=True)
    scenes = [c for c in chunks if c.kind == "scene"]
    assert [c.heading for c in scenes] == [
        "INT. KAMALA'S HOUSE - KITCHEN - DAWN",
        "EXT. KALUGALA HARBOUR - BREAKWATER - MORNING",
        "INT. AUCTION SHED - DAY",
        "EXT. KAMALA'S HOUSE - FRONT YARD - EVENING",
        "EXT. KALUGALA HARBOUR - NIGHT",
        "INT. KAMALA'S HOUSE - BEDROOM - NIGHT",
    ]
    assert "බෝට්ටුව විකුණන්න එපා." in scenes[3].content
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_markdown_chunks_follow_headings():
    ex = extract((CORPUS / "harbour-lights-bible.md").read_bytes(), "bible.md", "text/markdown")
    headings = [c.heading for c in chunking.chunk(ex, script_like=False)]
    assert "Premise" in headings and "Kamala (කමලා) — the mother" in headings


def test_long_sections_split_under_the_limit_with_overlap():
    paras = [f"Paragraph {i}. " + "The tide comes in and goes out again. " * 12 for i in range(30)]
    ex = extract(("# Long\n\n" + "\n\n".join(paras)).encode(), "long.md", "text/markdown")
    chunks = chunking.chunk(ex, script_like=False)
    assert len(chunks) > 3
    assert all(len(c.content) <= chunking.MAX_CHARS for c in chunks)
    assert all(c.heading == "Long" for c in chunks)


def test_one_giant_paragraph_is_still_split():
    ex = extract(("word " * 3000).encode(), "blob.txt", "text/plain")
    assert all(len(c.content) <= chunking.MAX_CHARS for c in chunking.chunk(ex, script_like=False))


def test_pdf_chunks_keep_page_ranges():
    pages = [f"INT. ROOM {i} - DAY\nSomeone walks in and sits down at the table by the window." for i in range(3)]
    ex = extract(make_pdf(pages), "s.pdf", "application/pdf")
    chunks = chunking.chunk(ex, script_like=True)
    assert [(c.page_start, c.page_end) for c in chunks] == [(1, 1), (2, 2), (3, 3)]
