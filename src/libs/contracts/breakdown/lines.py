"""Rule 1 of plan/2026-11-11 §3: the model points, code copies.

A document is a list of numbered lines (1-based). A model answers with line ranges and, inside a line, word ranges. Only
this module turns a pointer into text, so no spoken line can ever pass through a model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Words `w_from` up to (not including) `w_to` of one line. Words are whitespace-separated."""

    line: int
    w_from: int
    w_to: int


class Doc:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    @classmethod
    def from_text(cls, text: str) -> Doc:
        return cls([ln.rstrip("\r") for ln in text.split("\n")])

    def __len__(self) -> int:
        return len(self.lines)

    def has_line(self, n: int) -> bool:
        return 1 <= n <= len(self.lines)

    def numbered(self) -> str:
        return "\n".join(f"{i}: {ln}" for i, ln in enumerate(self.lines, 1))

    def cut(self, start: int, end: int) -> str:
        """Lines `start`..`end` inclusive, joined by newlines."""
        return "\n".join(self.lines[start - 1 : end])

    def words(self, n: int) -> list[str]:
        return self.lines[n - 1].split()

    def span_ok(self, s: Span) -> bool:
        return self.has_line(s.line) and 0 <= s.w_from < s.w_to <= len(self.words(s.line))

    def text(self, spans: list[Span]) -> str:
        return " ".join(" ".join(self.words(s.line)[s.w_from : s.w_to]) for s in spans)

    def find_line(self, needle: str, after: int = 0) -> int:
        """Gold-building helper (rehearsal answers only): the first line after `after` that starts with `needle`."""
        for i in range(after, len(self.lines)):
            if self.lines[i].strip().startswith(needle):
                return i + 1
        raise KeyError(needle)


def sentence_spans(doc: Doc, s: Span, lo: int, hi: int) -> list[Span]:
    """Widen a word span to the whole sentence it sits in, across wrapped lines, never leaving lines `lo`..`hi` (a
    card's own
    lines). A sentence ends at a word ending in . ? or !. Code widens; the model only points (rule 1)."""

    def ends(w: str) -> bool:
        return w.rstrip("\"')”’").endswith((".", "?", "!"))

    line, a = s.line, s.w_from
    while True:  # walk back to the word after the previous sentence's end
        if a > 0:
            if ends(doc.words(line)[a - 1]):
                break
            a -= 1
        elif line > lo and doc.words(line - 1):
            prev = doc.words(line - 1)
            if ends(prev[-1]) or len(prev) <= 2:  # the sentence before ended, or that line is only a label ("Nimal")
                break
            line -= 1
            a = len(prev)
        else:
            break
    first = Span(line, a, a)
    end_line, z = s.line, s.w_to
    while True:  # walk forward to the end of this sentence
        ws = doc.words(end_line)
        if z > 0 and ends(ws[z - 1]):
            break
        if z < len(ws):
            z += 1
        elif end_line < hi and doc.words(end_line + 1):
            end_line, z = end_line + 1, 0
        else:
            break
    out: list[Span] = []
    for n in range(first.line, end_line + 1):
        a0 = first.w_from if n == first.line else 0
        z0 = z if n == end_line else len(doc.words(n))
        if a0 < z0:
            out.append(Span(n, a0, z0))
    return out
