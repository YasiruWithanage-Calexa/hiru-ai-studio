"""The sentences of a spoken line (plan/2026-11-20 D2): ONE splitter for the clock and for line parts.

Omni Flash pauses about 0.75 to 1 s at every sentence end INSIDE a line (lab/sinhala_pace run 1), so the clock counts
one `SENTENCE_PAUSE_S` per break (`sentence_breaks`). A long line is covered in parts cut at those ends (`sentences`),
the script's words unchanged: joining the parts with single spaces gives the line back (its outer quotes and spacing
aside). Mirrors the interface's `src/lib/text/sentences.ts`; both are tested against `tests/contracts/sentences.json`.

    sentences("ඔව්. රුපියල් පන්දහසකින් පටන් ගත්තේ. තව ඉස්සරහට යන්න තමයි බලාපොරොත්තුව.")
        -> ["ඔව්. රුපියල් පන්දහසකින් පටන් ගත්තේ.", "තව ඉස්සරහට යන්න තමයි බලාපොරොත්තුව."]

A sentence ends after `.` `?` `!` or `…` (a closing quote may follow, and stays with it). A piece under
`MIN_PART_WORDS` words joins the next one ("ඔව්." keeps with its sentence); the last joins the one before. Pure stdlib.
"""

from __future__ import annotations

import re

MIN_PART_WORDS = 3  # a part shorter than this is not a part: it joins its neighbour
# A break is whitespace after a sentence end, or after a sentence end and its closing quote (the quote stays put).
_BREAK = re.compile(r"(?:(?<=[.?!…])|(?<=[.?!…][\"'”’]))\s+")
_OUTER_QUOTES = "\"“”'‘’"
_PARENTHETICAL = re.compile(r"\([^)]*\)")  # a stage direction is not speech (`contracts.timing.words_in`)


def body(text: str | None) -> str:
    """The line as it is said: spacing collapsed and the quotes around the whole line taken off, once."""
    out = " ".join(str(text or "").split())
    if len(out) >= 2 and out[0] in _OUTER_QUOTES and out[-1] in _OUTER_QUOTES:
        out = out[1:-1].strip()
    return out


def pieces(text: str | None) -> list[str]:
    """The line cut at every sentence end, nothing joined."""
    return [p for p in _BREAK.split(body(text)) if p.strip()]


def sentence_breaks(text: str | None) -> int:
    """How many sentence ends fall INSIDE the line (each is a pause on the clock). A stage direction in brackets does
    not count."""
    spoken = _PARENTHETICAL.sub(" ", body(text))
    return max(len([p for p in _BREAK.split(" ".join(spoken.split())) if p.strip()]) - 1, 0)


def sentences(text: str | None) -> list[str]:
    """The line's parts: cut after each sentence end; a piece under `MIN_PART_WORDS` words joins the next (the last
    joins the one before). One part for a line of one sentence."""
    merged: list[str] = []
    carry = ""
    for piece in pieces(text):
        piece = f"{carry} {piece}" if carry else piece
        carry = ""
        if len(piece.split()) < MIN_PART_WORDS:
            carry = piece
        else:
            merged.append(piece)
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged
