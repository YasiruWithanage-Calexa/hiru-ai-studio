"""The memory reader's entries against the document (plan/2026-11-05d M2). No model.

An entry is kept only when what it quotes is in the document, it says something, and what it applies to is one of the
five forms. Nothing is repaired or invented: a wrong entry is dropped and named in a warning, so a person sees what the
reader tried. Exact repeats are merged.
"""
from __future__ import annotations

import re
from typing import Any

from contracts.memory import STRENGTHS, parse_target, target_text, topic_key
from hiru_ai.core import parts

MAX_ENTRIES = 80  # one document; more is a reader that is listing the whole page, not its direction
MIN_QUOTE = 6  # characters after `flat`: a shorter "quote" would be found in any document
SHOWN_WARNINGS = 10
_ELLIPSIS = re.compile(r"\s*(?:\.{2,}|…)\s*")


def _flat(text: str) -> str:
    flat: str = parts.step("verbatim_check").flat(text)
    return flat


def quote_in(quote: str, flat_text: str) -> bool:
    """Are the quote's words in the document, in order? The reader copies exactly, but a quote cut short with an
    ellipsis ("shallow focus…") or one that skips a stretch ("lenses … shallow focus") is read as its pieces, each of
    which must be there, one after the other."""
    pieces = [p for p in (_flat(p).strip() for p in _ELLIPSIS.split(quote)) if p]
    if sum(len(p) for p in pieces) < MIN_QUOTE:
        return False
    at = 0
    for piece in pieces:
        found = flat_text.find(piece, at)
        if found < 0:
            return False
        at = found + len(piece)
    return True


def _why(entry: dict[str, Any], flat_text: str) -> str:
    """What is wrong with an entry, or "" when it is kept."""
    if not topic_key(str(entry.get("topic") or "")):
        return "no topic"
    if not str(entry.get("says") or "").strip():
        return "it says nothing"
    if entry.get("strength") not in STRENGTHS:
        return "strength is not must, prefer or fact"
    if parse_target(str(entry.get("applies_to") or "")) is None:
        return f"it applies to {str(entry.get('applies_to') or '')!r}, which is not production, place:, character:, " \
               "episode:<n> or when:"
    if not quote_in(str(entry.get("quote") or ""), flat_text):
        return "its quote is not in the document"
    return ""


def check(entries: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """-> `{"entries": the kept ones, "dropped": how many were not, "warnings": one line per dropped entry}`. The kept
    entries are in the reader's order, each with a clean topic and target."""
    flat_text = _flat(text)
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    warnings: list[str] = []
    dropped = 0
    for entry in entries:
        why = _why(entry, flat_text)
        says = " ".join(str(entry.get("says") or "").split())
        key = (topic_key(str(entry.get("topic") or "")), target_text(str(entry.get("applies_to") or "")).casefold(),
               _flat(says))
        if not why and key in seen:
            continue  # the same direction twice is one entry, not a drop
        if not why and len(kept) >= MAX_ENTRIES:
            why = f"more than {MAX_ENTRIES} entries from one document"
        if why:
            dropped += 1
            warnings.append(f"memory entry dropped ({why}): {says[:80]}")
            continue
        seen.add(key)
        kept.append({"topic": key[0], "applies_to": target_text(str(entry["applies_to"])), "says": says,
                     "quote": " ".join(str(entry["quote"]).split()), "strength": entry["strength"]})
    if len(warnings) > SHOWN_WARNINGS:
        warnings = [*warnings[:SHOWN_WARNINGS], f"{len(warnings) - SHOWN_WARNINGS} more memory entries were dropped"]
    return {"entries": kept, "dropped": dropped, "warnings": warnings}
