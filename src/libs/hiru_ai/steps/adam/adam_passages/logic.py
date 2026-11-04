"""Which passages of adam_film_grammar an agent is given (plan/2026-11-04b §5.2, §7).

    grammar   the principles that fit the scene (about 5), then the house drama notes, which are always relevant
    devices   the devices that fit the scene (about 8); each is one short file with its eight fields

Ranking is BM25 over each file's title and body with a crude stem, the same proxy `tests/adam/test_knowledge.py` holds
to ten probe questions. A scene with nothing to match still gets the first files in name order, so an agent is never
handed an empty section.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from hiru_ai.rag import knowledge

KB = "adam_film_grammar"
KINDS = ("grammar", "devices")
DEFAULT_K = {"grammar": 5, "devices": 8}
ALWAYS = {"grammar": ("house-drama-notes.md",), "devices": ()}
FOLDER = {"grammar": "principles", "devices": "devices"}
K1, B = 1.5, 0.75
STOP = frozenset(("a an and are as at be but by for from has have he her his i in is it its of on or she so that the "
                  "their them then they this to was we were what when where which who will with you your").split())


def stem(word: str) -> str:
    for tail in ("ing", "ed", "es", "s"):
        if word.endswith(tail) and len(word) - len(tail) >= 3:
            return word[: -len(tail)]
    return word


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP and len(w) > 2]


def body_of(text: str) -> tuple[str, str]:
    """(title, body) of a source file: the front matter's title, and the text after it."""
    title = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head, text = text[3:end], text[end + 4:]
            found = re.search(r'^title:\s*"?(.+?)"?\s*$', head, re.M)
            title = found.group(1) if found else ""
    return title, text.strip()


@lru_cache(maxsize=1)
def _sources() -> Path:
    return knowledge.load(KB).sources


@lru_cache(maxsize=2)
def _library(kind: str) -> tuple[tuple[str, str, str], ...]:
    """(file, title, body) of every file of a kind, in name order."""
    rows = []
    for path in sorted((_sources() / FOLDER[kind]).glob("*.md")):
        title, body = body_of(path.read_text(encoding="utf-8"))
        rows.append((f"{FOLDER[kind]}/{path.name}", title or path.stem.replace("-", " "), body))
    return tuple(rows)


def rank(query: str, docs: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """The docs best first. A doc with no match keeps its place in name order after those that match."""
    want = set(tokens(query))
    counts = [Counter(tokens(f"{title} {title} {body}")) for _, title, body in docs]
    avg = (sum(sum(c.values()) for c in counts) / len(counts)) or 1.0
    scores = []
    for c in counts:
        length = sum(c.values()) or 1
        s = 0.0
        for term in want:
            tf = c.get(term, 0)
            if not tf:
                continue
            df = sum(1 for other in counts if term in other)
            idf = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
            s += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg))
        scores.append(s)
    order = sorted(range(len(docs)), key=lambda i: (-scores[i], i))
    return [docs[i] for i in order]


def passages(query: str, kind: str, k: int) -> dict[str, object]:
    docs = list(_library(kind))
    picked = rank(query, docs)[: max(1, k)]
    extra = [d for d in _read_always(kind) if d[0] not in {p[0] for p in picked}]
    chosen = [*picked, *extra]
    text = "\n\n".join(f"## {title}\n{body}" for _, title, body in chosen)
    return {"text": text, "sources": [f for f, _, _ in chosen], "kind": kind}


def _read_always(kind: str) -> list[tuple[str, str, str]]:
    out = []
    for name in ALWAYS[kind]:
        path = _sources() / name
        if path.exists():
            title, body = body_of(path.read_text(encoding="utf-8"))
            out.append((name, title or path.stem.replace("-", " "), body))
    return out
