"""A dialogue operation may only use words the person wrote (a removal carries none)."""
from __future__ import annotations

# Ported from services/director_chat/director_chat/engine/turn.py (plan/2026-11-03 Phase 2).
import difflib
import re
import unicodedata
from typing import Any


def flat(text: str) -> str:
    """Words as a person typed them, for comparing: NFC, any case, plain quotes, one spaced ellipsis."""
    table = {"“": '"', "”": '"', "‘": "'", "’": "'", "…": "..."}
    flat = unicodedata.normalize("NFC", str(text))
    for k, v in table.items():
        flat = flat.replace(k, v)
    return " ".join(re.sub(r"\s*\.{2,}\s*", " ... ", flat.casefold()).split())


def words(text: str) -> list[str]:
    return [w for w in (x.strip(" .,!?;:\"'()-—@") for x in flat(text).split()) if w]


def verbatim(op: dict[str, Any], flat_written: str, pool: set[str]) -> bool:
    """A dialogue operation's words must be ones the person wrote (a removal carries none): the
    same run of words, or each word theirs (a longer word may be a typo away, so fixing "restarunt"
    is theirs; a word they never wrote is not)."""
    if op.get("op") == "block.remove":
        return True

    def theirs(w: str) -> bool:
        return w in pool or (len(w) >= 5 and bool(difflib.get_close_matches(w, pool, n=1, cutoff=0.8)))

    said = [op.get("value"), op.get("speaker"), op.get("delivery")]
    return all(flat(str(w)) in flat_written or all(theirs(x) for x in words(str(w)))
               for w in said if str(w or "").strip())
