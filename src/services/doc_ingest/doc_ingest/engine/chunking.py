"""Lines → chunks. Structure first, size second.

1. Split into SECTIONS along the document's own structure: scene headings in a screenplay,
   `#` headings in Markdown. A scene is the unit people ask about ("what happens in the harbour
   scene?"), so a chunk boundary inside a scene is a retrieval miss waiting to happen.
2. Only a section longer than MAX_CHARS is split, on paragraph boundaries (then sentences,
   then hard), carrying a short overlap so a sentence cut at the boundary is findable from
   both sides.

Every chunk keeps the page range it came from, for citations.

Also used by `scripts/ingest_knowledge.py` for the craft corpus, so there is one chunker.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass

from doc_ingest.engine.extract import Extracted, Line
from doc_ingest.engine.roles import SCENE_HEADING

MAX_CHARS = 2400  # ~600 English tokens; Sinhala costs more tokens per character, still well inside limits
OVERLAP_CHARS = 300
MIN_CHARS = 40  # fragments shorter than this merge into a neighbour

_MD_HEADING = re.compile(r"^\s{0,3}(#{1,3})\s+(.+?)\s*#*\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


@dataclass
class Chunk:
    ord: int
    heading: str
    content: str
    page_start: int | None
    page_end: int | None
    kind: str  # "scene" | "section" | "passage"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.heading}\n{self.content}".encode()).hexdigest()


@dataclass
class _Section:
    heading: str
    lines: list[Line]
    kind: str


def _split_sections(lines: list[Line], *, scenes: bool, markdown: bool) -> list[_Section]:
    sections: list[_Section] = [_Section("", [], "passage")]
    for line in lines:
        md = _MD_HEADING.match(line.text) if markdown else None
        if scenes and SCENE_HEADING.match(line.text):
            sections.append(_Section(line.text.strip(), [line], "scene"))
        elif md:
            sections.append(_Section(md.group(2).strip(), [], "section"))
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if any(ln.text.strip() for ln in s.lines) or s.heading]


def _paragraphs(lines: list[Line]) -> list[list[Line]]:
    paras: list[list[Line]] = [[]]
    for line in lines:
        if line.text.strip():
            paras[-1].append(line)
        elif paras[-1]:
            paras.append([])
    return [p for p in paras if p]


def _text(lines: Iterable[Line]) -> str:
    return "\n".join(ln.text for ln in lines).strip()


def _pages(lines: list[Line]) -> tuple[int | None, int | None]:
    pages = [ln.page for ln in lines if ln.page is not None]
    return (min(pages), max(pages)) if pages else (None, None)


def _hard_split(para: list[Line]) -> list[list[Line]]:
    """A single paragraph over MAX_CHARS: split by sentences, then by characters."""
    page = para[0].page
    pieces: list[str] = []
    buf = ""
    for sentence in _SENTENCE_END.split(_text(para)):
        while len(sentence) > MAX_CHARS:
            pieces.append(sentence[:MAX_CHARS])
            sentence = sentence[MAX_CHARS:]
        if buf and len(buf) + len(sentence) + 1 > MAX_CHARS:
            pieces.append(buf)
            buf = ""
        buf = f"{buf} {sentence}".strip()
    if buf:
        pieces.append(buf)
    return [[Line(p, page)] for p in pieces]


def _pack(section: _Section) -> list[list[Line]]:
    """Group a section's paragraphs into pieces of at most MAX_CHARS, with overlap."""
    paras: list[list[Line]] = []
    for p in _paragraphs(section.lines):
        paras.extend(_hard_split(p) if len(_text(p)) > MAX_CHARS else [p])
    pieces: list[list[Line]] = []
    current: list[Line] = []
    for para in paras:
        if current and len(_text(current)) + len(_text(para)) + 2 > MAX_CHARS:
            pieces.append(current)
            tail = current[-1:]  # overlap: the last paragraph, when it is short enough
            current = list(tail) if len(_text(tail)) <= OVERLAP_CHARS else []
        current = [*current, Line(""), *para] if current else list(para)
    if current:
        pieces.append(current)
    return pieces


def chunk(extracted: Extracted, *, script_like: bool) -> list[Chunk]:
    scene_count = sum(1 for ln in extracted.lines if SCENE_HEADING.match(ln.text))
    sections = _split_sections(
        extracted.lines,
        scenes=script_like or scene_count >= 2,
        markdown=extracted.kind == "markdown" or any(_MD_HEADING.match(ln.text) for ln in extracted.lines[:200]),
    )
    out: list[Chunk] = []
    for section in sections:
        for piece in _pack(section):
            content = _text(piece)
            if not content:
                continue
            start, end = _pages(piece)
            if out and len(content) < MIN_CHARS and out[-1].heading == section.heading:
                prev = out[-1]  # a stray fragment joins the chunk before it
                prev.content = f"{prev.content}\n{content}"
                prev.page_end = end or prev.page_end
                continue
            out.append(Chunk(len(out), section.heading, content, start, end, section.kind))
    return out
