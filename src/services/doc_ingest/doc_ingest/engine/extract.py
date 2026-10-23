"""Bytes → normalised lines of text, each tagged with its page (PDF) or None.

Accepted (PLAN.md Q8): text-layer PDF, Markdown, plain text / Fountain. No OCR: a PDF without
a text layer is REJECTED with a message the uploader can act on, never indexed as nothing.

Sinhala notes, both load-bearing:
* Text is normalised to NFC, but ZERO WIDTH JOINER / NON-JOINER are KEPT. Sinhala writes
  yansaya, rakaransaya and touching letters with ZWJ (ශ්‍රී = ශ + ් + ZWJ + ර + ී); stripping
  "invisible characters" would change the words.
* Many Sri Lankan PDFs are typed in legacy fonts (FM Abhaya and similar) that draw Sinhala
  glyphs over Latin code points. Their text layer extracts as Latin gibberish. That cannot be
  detected with certainty, so the pipeline WARNS (see `pipeline.legacy_font_warning`) instead
  of indexing it silently.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["pdf", "markdown", "text"]

MAX_CHARS = 2_000_000  # ~1,000 script pages; beyond this something is wrong with the file
_SCANNED_MIN_CHARS_PER_PAGE = 40
_SCANNED_EMPTY_PAGE_RATIO = 0.6
_EMPTY_PAGE_CHARS = 20
_SINHALA = re.compile(r"[඀-෿]")


class Rejected(Exception):
    """The file cannot be used as given. The message is shown to the uploader."""


@dataclass(frozen=True)
class Line:
    text: str
    page: int | None = None


@dataclass
class Extracted:
    kind: Kind
    lines: list[Line]
    page_count: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def char_count(self) -> int:
        return sum(len(line.text) for line in self.lines)

    @property
    def has_sinhala(self) -> bool:
        return any(_SINHALA.search(line.text) for line in self.lines)


def normalise(text: str) -> str:
    """NFC, unified newlines, no NUL or BOM. ZWJ (U+200D) and ZWNJ (U+200C) are kept."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").replace("﻿", "")
    text = unicodedata.normalize("NFC", text)
    # Collapse runs of spaces/tabs but never touch newlines (structure lives in them).
    return re.sub(r"[ \t ]+", " ", text)


def kind_for(filename: str, mime_type: str) -> Kind:
    name = filename.lower()
    if name.endswith(".pdf") or mime_type == "application/pdf":
        return "pdf"
    if name.endswith((".md", ".markdown")) or mime_type == "text/markdown":
        return "markdown"
    return "text"


def extract(data: bytes, filename: str, mime_type: str) -> Extracted:
    kind = kind_for(filename, mime_type)
    result = _extract_pdf(data) if kind == "pdf" else _extract_text(data, kind)
    if result.char_count > MAX_CHARS:
        raise Rejected("This file has more text than one document can hold. Split it into parts "
                       "(for example one file per episode) and upload them separately.")
    if not any(line.text.strip() for line in result.lines):
        raise Rejected("This file has no text in it.")
    return result


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if b"\x00" in data[:4096]:
        raise Rejected("This does not look like a text file. Upload a PDF, Markdown or plain "
                       "text file.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Rejected("This text file is not saved as UTF-8 (Unicode). Save it again with "
                       "UTF-8 encoding and upload it.") from None


def _extract_text(data: bytes, kind: Kind) -> Extracted:
    text = normalise(_decode(data))
    return Extracted(kind=kind, lines=[Line(t) for t in text.split("\n")])


def _extract_pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if not data.startswith(b"%PDF"):
        raise Rejected("This file is not a valid PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise Rejected("This PDF is password-protected. Remove the password and upload it again.")
        pages = [normalise(page.extract_text() or "") for page in reader.pages]
    except Rejected:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise Rejected("This PDF could not be read. Export it again from the original "
                       "document and upload the new file.") from exc

    if not pages:
        raise Rejected("This PDF has no pages.")
    total = sum(len(p.strip()) for p in pages)
    empty = sum(1 for p in pages if len(p.strip()) < _EMPTY_PAGE_CHARS)
    if total < _SCANNED_MIN_CHARS_PER_PAGE * len(pages) or empty / len(pages) >= _SCANNED_EMPTY_PAGE_RATIO:
        raise Rejected("This PDF has no readable text layer (it looks scanned). Upload a PDF "
                       "exported from the original document, or a Markdown or plain text file.")

    lines = [Line(t, page=i + 1) for i, page in enumerate(pages) for t in page.split("\n")]
    return Extracted(kind="pdf", lines=lines, page_count=len(pages))
