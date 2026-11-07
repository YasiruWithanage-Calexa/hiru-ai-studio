"""Is a PDF's text good enough to read, and where are its episodes? (plan/2026-11-06f §4.1, §4.2). Pure code.

Text quality. Some PDFs carry a broken text layer: Apple's Sinhala Sangam MN stores the split vowel signs wrongly in its
ToUnicode map, so `කොළඹ` comes out as `බෙක7ළඹ`. The Sinhala code points are there (the old "no Sinhala at all" warning
does not fire) but in the wrong order, with ASCII digits and symbols glued inside the words. A page is `corrupt` when
more than `CORRUPT_SHARE` of its Sinhala words hold such a character; a document with `PAGES_MODE_SHARE` or more corrupt
pages is read from its page images. Measured on the person's two files and every Sinhala fixture in the repo: clean
Sinhala scores 0 on every page, the corrupt file 0.11 to 0.89 on every page.

Pieces. One episode per call. Boundaries come from the text layer: `SEASON ONE EPISODE 01` and `EPISODE 01` survive the
corruption (their Latin part does). An index page (three or more episode numbers on one page) is not a boundary, and
only the first time a number appears counts, in rising order, so running headers and "END OF EPISODE 01" never split.
With no boundaries, windows of `WINDOW_PAGES` pages that overlap by one page; the model says which episode each
scene is in.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

CORRUPT_SHARE = 0.05
PAGES_MODE_SHARE = 0.20
MIN_WORDS = 5  # a page with fewer Sinhala words says nothing about the font
WINDOW_PAGES = 12
SHORT_PAGES = 8  # a document this short is ONE call that returns its canon and its episodes (decision 3)
CANON_PAGES = 60  # the most pages one canon call reads (a long bible is read in windows)

_SINHALA = re.compile(r"[\u0D80-\u0DFF]")
_GLUED = re.compile(r"[\u0D80-\u0DFF\u200c\u200d][0-9A-Za-z\[\]<>=\\{}|~^`@#$%&*+/_]"
                    r"|[0-9A-Za-z\[\]<>=\\{}|~^`@#$%&*+/_][\u0D80-\u0DFF]")
_EPISODE_LINE = re.compile(r"^\s*#*\s*(?:SEASON\s+\S+\s+)?(?:EPISODE|EP\.?|කථාංගය)\s*0*(\d{1,3})\b(?!\s*:\d)",
                           re.IGNORECASE)
_NOT_A_HEADING = re.compile(r"^\s*(?:END|CONTINUITY|PREVIOUSLY|NEXT|STARTING|FROM)\b", re.IGNORECASE)
MAX_HEADING_CHARS = 70


@dataclass
class PageQuality:
    page: int  # 1-based
    sinhala_words: int
    glued: int

    @property
    def share(self) -> float:
        return self.glued / self.sinhala_words if self.sinhala_words else 0.0

    @property
    def corrupt(self) -> bool:
        return self.sinhala_words >= MIN_WORDS and self.share > CORRUPT_SHARE


def page_quality(page: int, text: str) -> PageQuality:
    words = [w for w in text.split() if _SINHALA.search(w)]
    return PageQuality(page, len(words), sum(1 for w in words if _GLUED.search(w)))


@dataclass
class Quality:
    pages: list[PageQuality]

    @property
    def corrupt_pages(self) -> list[int]:
        return [p.page for p in self.pages if p.corrupt]

    @property
    def judged(self) -> int:
        """Pages with enough Sinhala to judge the font by."""
        return sum(1 for p in self.pages if p.sinhala_words >= MIN_WORDS)

    @property
    def mode(self) -> str:
        """`pages` when the text layer cannot be trusted, else `text`."""
        judged = self.judged
        return "pages" if judged and len(self.corrupt_pages) / judged >= PAGES_MODE_SHARE else "text"


def quality(pages: list[str]) -> Quality:
    """`pages`: the text of each page, in order (the stored text split on form feeds)."""
    return Quality([page_quality(i, t) for i, t in enumerate(pages, start=1)])


SCRAMBLED_WARNING = ("The Sinhala text inside this PDF is scrambled: its font stores the vowel signs in the wrong "
                     "order (for example කොළඹ is stored as බෙක7ළඹ), so no program can read the text as it is. The "
                     "reader reads it from the page images instead, and its dialogue must be checked by a person. For "
                     "an exact reading, export the script again from Word or Google Docs with a Unicode Sinhala font "
                     "(Noto Sans Sinhala or Iskoola Pota).")


# ── pieces ────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Piece:
    """A run of pages (and of global line numbers) that one model call reads."""
    kind: str  # "front" (before the first episode), "episode", "window", "whole"
    first_page: int
    last_page: int
    first_line: int  # 1-based global line numbers, inclusive (text mode)
    last_line: int
    episode: int | None = None  # the episode this piece is, when the text says
    title: str = ""
    expect: list[int] = field(default_factory=list)  # the episodes the answer must hold


@dataclass
class Layout:
    lines: list[str]  # every line of the document, in order (page breaks removed)
    page_of: list[int]  # the 1-based page of each line
    pages: int

    def first_line_of(self, page: int) -> int:
        return next((i + 1 for i, p in enumerate(self.page_of) if p >= page), len(self.lines) + 1)

    def last_line_of(self, page: int) -> int:
        return max((i + 1 for i, p in enumerate(self.page_of) if p <= page), default=0)


def layout(text: str) -> Layout:
    """The stored text (pages separated by form feeds) as numbered lines with their pages."""
    pages = text.split("\f")
    lines: list[str] = []
    page_of: list[int] = []
    for n, page in enumerate(pages, start=1):
        for line in page.split("\n"):
            lines.append(line)
            page_of.append(n)
    return Layout(lines, page_of, len(pages))


@dataclass
class Boundary:
    episode: int
    line: int  # 1-based global line
    page: int
    title: str = ""


_TITLE = re.compile(r"[\"“”]\s*([^\"“”]+?)\s*[\"“”]")


def boundaries(doc: Layout) -> list[Boundary]:
    """The line each episode starts at: the first time its number appears as a heading, in rising order."""
    found: list[Boundary] = []
    per_page: dict[int, set[int]] = {}
    hits: list[tuple[int, int, int, str]] = []
    for i, line in enumerate(doc.lines):
        if len(line.strip()) > MAX_HEADING_CHARS or _NOT_A_HEADING.match(line):
            continue
        m = _EPISODE_LINE.match(line)
        if m:
            number, page = int(m.group(1)), doc.page_of[i]
            per_page.setdefault(page, set()).add(number)
            hits.append((number, i + 1, page, line))
    index_pages = {p for p, numbers in per_page.items() if len(numbers) >= 3}
    last = 0
    for number, line_no, page, text in hits:
        if page in index_pages or number <= last:
            if found and number == found[-1].episode and not found[-1].title:
                found[-1].title = _title(text)  # "Episode 01: “11:17”" right after "SEASON ONE EPISODE 01"
            continue
        found.append(Boundary(number, line_no, page, _title(text)))
        last = number
    return found


def _title(line: str) -> str:
    m = _TITLE.search(line)
    return m.group(1).strip() if m else ""


def pieces(doc: Layout, *, role: str) -> list[Piece]:
    """How a document is read: a short document whole; a script as its front pages then one piece per episode (or
    windows); a bible, a canon index or an outline as canon windows."""
    n = len(doc.lines)
    if doc.pages <= SHORT_PAGES:
        return [Piece("whole", 1, doc.pages, 1, n)]
    if role != "script":
        return [Piece("front", a, b, doc.first_line_of(a), doc.last_line_of(b))
                for a, b in _windows(1, doc.pages, CANON_PAGES, overlap=0)]
    marks = boundaries(doc)
    if not marks:
        return [Piece("window", a, b, doc.first_line_of(a), doc.last_line_of(b))
                for a, b in _windows(1, doc.pages, WINDOW_PAGES, overlap=1)]
    out: list[Piece] = []
    if marks[0].line > 1:
        out.append(Piece("front", 1, doc.page_of[marks[0].line - 2] if marks[0].line > 1 else 1, 1,
                         marks[0].line - 1))
    for k, mark in enumerate(marks):
        end_line = marks[k + 1].line - 1 if k + 1 < len(marks) else n
        out.append(Piece("episode", mark.page, doc.page_of[end_line - 1], mark.line, end_line,
                         episode=mark.episode, title=mark.title, expect=[mark.episode]))
    return out


def _windows(first: int, last: int, size: int, *, overlap: int) -> list[tuple[int, int]]:
    out, start = [], first
    while start <= last:
        end = min(last, start + size - 1)
        out.append((start, end))
        if end == last:
            break
        start = end + 1 - overlap
    return out


def halves(piece: Piece, doc: Layout, is_heading: Callable[[str], bool] | None = None) -> tuple[Piece, Piece] | None:
    """A piece cut in two when its answer was too long (§8): at the scene heading nearest the middle in text mode
    (`is_heading(line)`), else at the middle page. None when it cannot be cut (one page)."""
    test = is_heading
    mid_line = (piece.first_line + piece.last_line) // 2
    cut: int | None = None
    if test is not None:
        heads = [i for i in range(piece.first_line + 1, piece.last_line + 1) if test(doc.lines[i - 1])]
        if heads:
            cut = min(heads, key=lambda i: abs(i - mid_line))
    if cut is None:
        if piece.first_page >= piece.last_page:
            return None
        mid_page = (piece.first_page + piece.last_page + 1) // 2
        cut = doc.first_line_of(mid_page)
    if cut <= piece.first_line or cut > piece.last_line:
        return None
    a = Piece(piece.kind, piece.first_page, doc.page_of[cut - 2], piece.first_line, cut - 1, piece.episode,
              piece.title, list(piece.expect))
    b = Piece(piece.kind, doc.page_of[cut - 1], piece.last_page, cut, piece.last_line, piece.episode, piece.title,
              list(piece.expect))
    return a, b
