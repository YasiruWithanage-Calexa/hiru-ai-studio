"""The quote guard (plan/2026-11-08 §4.1 GUARD, rule 4 "dialogue is verbatim"). Pure code, no model.

A reply may quote a spoken line only exactly as a tool returned it. Every quoted span that looks like a line (any
Sinhala letter, or four words or more) must appear in what the tools returned or in what the person themselves
wrote; a span that does not is taken out with the sentence that carries it, and the guard says what it took out (it
goes into the turn's record, never to the browser). Matching is on NFC text with spacing folded, so a line copied byte
for byte from a tool passes and a line "tidied" by a model does not.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

QUOTES = re.compile(r"“([^”]{2,600})”|\"([^\"]{2,600})\"|‘([^’]{2,600})’")
SINHALA = re.compile(r"[඀-෿]")
MIN_WORDS = 4
SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")
REMOVED = "(I left out a line I could not read back from the script.)"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().casefold()


def looks_like_a_line(span: str) -> bool:
    return bool(SINHALA.search(span)) or len(span.split()) >= MIN_WORDS


def quotes(text: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in QUOTES.finditer(text)]


def check(text: str, sources: Iterable[str]) -> tuple[str, list[str]]:
    """-> (the reply with every unbacked line-like quote taken out, what was taken out). `sources` are the tool results
    and the person's own words; a quote found in any of them stands."""
    pool = _norm("\n".join(sources))
    bad = [q for q in quotes(text) if looks_like_a_line(q) and _norm(q) not in pool]
    if not bad:
        return text, []
    kept: list[str] = []
    for sentence in SENTENCE.findall(text):
        if sentence and not any(q in sentence for q in bad):
            kept.append(sentence)
    out = "".join(kept).strip()
    out = f"{out} {REMOVED}".strip() if out else REMOVED
    return re.sub(r"[ \t]{2,}", " ", out), [f"removed a quote no tool returned: {q[:80]}" for q in bad]
