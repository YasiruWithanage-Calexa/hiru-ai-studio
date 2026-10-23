from __future__ import annotations

import unicodedata

import pytest
from doc_ingest.engine.extract import Rejected, extract, normalise

from tests.services.doc_ingest.conftest import make_pdf


def test_utf8_text_and_markdown_kinds():
    assert extract(b"hello\nworld", "a.txt", "text/plain").kind == "text"
    assert extract(b"# Title\nbody", "a.md", "text/markdown").kind == "markdown"


def test_utf16_with_bom_is_accepted():
    data = "නිමල් ආවා".encode("utf-16")
    assert extract(data, "a.txt", "text/plain").text == "නිමල් ආවා"


def test_non_utf8_text_is_rejected_with_a_fix():
    with pytest.raises(Rejected, match="UTF-8"):
        extract("café".encode("latin-1"), "a.txt", "text/plain")


def test_binary_disguised_as_text_is_rejected():
    with pytest.raises(Rejected, match="not look like a text file"):
        extract(b"PK\x03\x04\x00\x00binary", "a.txt", "text/plain")


def test_empty_file_is_rejected():
    with pytest.raises(Rejected, match="no text"):
        extract(b"   \n\n ", "a.txt", "text/plain")


def test_nfc_normalisation_composes_decomposed_text():
    decomposed = unicodedata.normalize("NFD", "කෝ")
    assert normalise(decomposed) == unicodedata.normalize("NFC", "කෝ")


def test_zero_width_joiner_is_kept_for_sinhala_conjuncts():
    shri = "ශ්‍රී ලංකාව"
    assert "‍" in extract(shri.encode(), "a.txt", "text/plain").text


def test_pdf_lines_carry_page_numbers():
    pdf = make_pdf(["Page one has enough text to count as a real text layer, honestly.",
                    "Page two also has a full sentence of readable text on it here."])
    out = extract(pdf, "doc.pdf", "application/pdf")
    assert out.kind == "pdf" and out.page_count == 2
    assert {ln.page for ln in out.lines if ln.text.strip()} == {1, 2}
    assert "Page two" in out.text


def test_scanned_pdf_is_rejected():
    with pytest.raises(Rejected, match="scanned"):
        extract(make_pdf(["", "", ""]), "scan.pdf", "application/pdf")


def test_mostly_empty_pdf_is_rejected():
    pages = ["A real page of text that is long enough to be counted as content here."] + [""] * 4
    with pytest.raises(Rejected, match="scanned"):
        extract(make_pdf(pages), "scan.pdf", "application/pdf")


def test_not_a_pdf_is_rejected():
    with pytest.raises(Rejected, match="not a valid PDF"):
        extract(b"hello", "x.pdf", "application/pdf")


def test_corrupt_pdf_is_rejected():
    with pytest.raises(Rejected):
        extract(b"%PDF-1.4\nthis is not really a pdf", "x.pdf", "application/pdf")
