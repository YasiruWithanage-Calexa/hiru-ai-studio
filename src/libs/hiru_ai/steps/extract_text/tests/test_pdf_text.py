"""pdf_text (plan/2026-11-15 phase 1): /ActualText is honoured, so Sinhala drawn in visual order comes out as
the Unicode the PDF stores for it. A tiny PDF is built here: the glyphs "XY" are drawn inside a span whose ActualText is
"ගේ", as Chrome/Skia write a Sinhala cluster."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from hiru_ai.steps.extract_text import pdf_text

CONTENT = (
    "BT /F1 12 Tf 72 720 Td (Api ) Tj "
    "/Span <</ActualText <FEFF0D9C0DDA>>> BDC (XY) Tj EMC "
    "ET "
    "BT /F1 12 Tf 72 700 Td (Second line) Tj ET "
    "BT /F1 12 Tf 72 680 Td /Span <</ActualText <FEFF0DB8>>> BDC (Q) Tj EMC ( and   more) Tj ET"
)


def _pdf() -> bytes:
    w = PdfWriter()
    page = w.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(CONTENT.encode("latin-1"))
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_the_walker_writes_the_actual_text_in_place_of_the_glyphs() -> None:
    assert pdf_text.pages(_pdf(), use="walker") == [["Api ගේ", "Second line", "ම and more"]]


def test_pypdfs_own_extraction_reads_the_glyphs_which_is_the_bug_fixed() -> None:
    text = PdfReader(io.BytesIO(_pdf())).pages[0].extract_text()
    assert "XY" in text and "ගේ" not in text


def test_the_engine_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_TEXT__ENGINE", "walker")
    assert pdf_text.engine() == "walker"
    monkeypatch.setenv("PDF_TEXT__ENGINE", "poppler")
    assert pdf_text.engine() == "poppler"


def test_auto_uses_poppler_only_when_it_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDF_TEXT__ENGINE", "auto")
    monkeypatch.setattr(pdf_text.shutil, "which", lambda _: None)
    assert pdf_text.engine() == "walker"
    monkeypatch.setattr(pdf_text.shutil, "which", lambda _: "/usr/bin/pdftotext")
    assert pdf_text.engine() == "poppler"


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is not installed here")
def test_poppler_reads_the_same_lines_as_the_walker() -> None:
    assert pdf_text.pages(_pdf(), use="poppler") == pdf_text.pages(_pdf(), use="walker")


def test_the_two_engines_carry_the_same_reader() -> None:
    """The service's copy (its zip carries only its own folder and contracts) is byte-identical to this one."""
    here = Path(pdf_text.__file__).resolve()
    service = here.parents[4] / "services" / "doc_ingest" / "doc_ingest" / "engine" / "pdf_text.py"
    assert here.read_text(encoding="utf-8").splitlines() == service.read_text(encoding="utf-8").splitlines()
