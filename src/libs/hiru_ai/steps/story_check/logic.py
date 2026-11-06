"""The reader's answer, checked against the document (plan/2026-11-05c S2). No model.

The `story_reader` agent quotes the text: where each episode starts and ends, every spoken line, the text that is not
story. Here every quote must be found in the document, in order, or it is dropped and counted. What is kept is then cut
from the source itself, so an episode's body and a spoken line are always the person's words, never the model's.

A quote is found by its letters, marks and digits only (any case, any quote or dash style, any spacing), as whole words,
so `“Miss! Your phone!”` in the document matches `Miss, your phone` from the model only if the words agree.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from bisect import bisect_left
from typing import Any

VERSION = 1
STORY_FILE = "story.json"  # beside `extracted.txt`
MIN_IGNORE = 4  # a shorter quote to leave out would match inside story text

_LINE_END = ".!?…"  # kept after a spoken line: part of how it is said
_EPISODE_END = ".!?…\"“”'’*_)"  # kept after an episode's last words: closing quotes and bold marks
_QUOTES = " \n\t\"“”‘’'"  # round a gap: the quote marks that open and close a spoken line


def _kept(ch: str) -> bool:
    return unicodedata.category(ch)[0] in "LMN"


def fold(text: str) -> str:
    """Letters, marks and digits of `text`, in lower case: what two spellings of one quote have in common."""
    return "".join(c for ch in unicodedata.normalize("NFC", text) if _kept(ch) for c in ch.casefold())


class Doc:
    """A document folded for finding quotes in it, with each folded character remembering its place in the source."""

    def __init__(self, text: str) -> None:
        self.src = unicodedata.normalize("NFC", text)
        key: list[str] = []
        self.at: list[int] = []
        for i, ch in enumerate(self.src):
            if _kept(ch):
                for c in ch.casefold():
                    key.append(c)
                    self.at.append(i)
        self.key = "".join(key)

    def find(self, quote: str, lo: int = 0, hi: int | None = None) -> tuple[int, int] | None:
        """(start, end) in the folded text of the first whole-word occurrence of `quote` inside [lo, hi)."""
        needle = fold(quote)
        if not needle:
            return None
        hi = len(self.key) if hi is None else hi
        i = self.key.find(needle, lo, hi)
        while i != -1:
            if self._whole(i, i + len(needle)):
                return i, i + len(needle)
            i = self.key.find(needle, i + 1, hi)
        return None

    def _whole(self, k0: int, k1: int) -> bool:
        s0, s1 = self.at[k0], self.at[k1 - 1] + 1
        return ((s0 == 0 or not _kept(self.src[s0 - 1]))
                and (s1 >= len(self.src) or not _kept(self.src[s1])))

    def key_at(self, offset: int) -> int:
        """The folded position of the first kept character at or after `offset` of the source."""
        return bisect_left(self.at, offset)

    def span(self, k0: int, k1: int, trail: str = "") -> tuple[int, int]:
        """The source offsets of a folded range, widened over `trail` characters that follow it."""
        s0, s1 = self.at[k0], self.at[k1 - 1] + 1
        while s1 < len(self.src) and self.src[s1] in trail:
            s1 += 1
        return s0, s1

    def words(self, k0: int, k1: int, trail: str = "") -> str:
        s0, s1 = self.span(k0, k1, trail)
        return " ".join(self.src[s0:s1].split())


def text_sha(text: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", text).encode("utf-8")).hexdigest()


def story_path(text_path: str) -> str:
    """Where a document's reading is kept: the folder of its `extracted.txt`."""
    folder = text_path.rpartition("/")[0]
    return f"{folder}/{STORY_FILE}" if folder else STORY_FILE


def dumps(story: dict[str, Any]) -> str:
    return json.dumps(story, ensure_ascii=False, indent=1)


def loads(raw: str, text: str) -> dict[str, Any] | None:
    """A saved reading, if it is one of this version and was made from exactly this text."""
    try:
        story = json.loads(raw)
    except ValueError:
        return None
    ok = isinstance(story, dict) and story.get("version") == VERSION and story.get("sha") == text_sha(text)
    return story if ok else None


def _plural(n: int, what: str) -> str:
    return f"{n} {what}{'' if n == 1 else 's'}"


def _slices(doc: Doc, episodes: list[dict[str, Any]], warnings: list[str]) -> list[tuple[int, int, dict[str, Any]]]:
    """(start, end) in the folded text and the reader's episode, in document order. An episode whose anchors are not
    in the text or out of order is dropped; one that runs into the next is cut where the next begins; a number the
    document has twice (a contents list, then the body) keeps the longer."""
    found: list[tuple[int, int, dict[str, Any]]] = []
    floor = 0
    for ep in episodes:
        start = doc.find(ep["starts_with"], floor)
        end = doc.find(ep["ends_with"], start[0]) if start else None
        label = f"episode {ep['number']}" if ep["number"] is not None else "an episode"
        if not start or not end:
            warnings.append(f"The reader's start or end of {label} is not in the document; it was left out.")
            continue
        found.append((start[0], end[1], ep))
        floor = start[0] + 1
    by_number: dict[int | None, tuple[int, int, dict[str, Any]]] = {}
    for item in found:
        number = item[2]["number"]
        if number not in by_number or item[1] - item[0] > by_number[number][1] - by_number[number][0]:
            by_number[number] = item
    kept = sorted(by_number.values(), key=lambda item: item[0])
    return [(a, min(b, kept[i + 1][0]) if i + 1 < len(kept) else b, ep) for i, (a, b, ep) in enumerate(kept)]


def _lines(doc: Doc, k0: int, k1: int,
           spoken: list[dict[str, Any]]) -> tuple[list[tuple[int, int, dict[str, str]]], int]:
    """The spoken lines the reader quoted that are in [k0, k1), in document order, as the source has them: (start, end
    in the folded text, line)."""
    kept: dict[int, tuple[int, int, dict[str, str]]] = {}
    cursor = k0
    for line in spoken:
        hit = doc.find(line["text"], cursor, k1) or doc.find(line["text"], k0, k1)
        if not hit:
            continue
        cursor = hit[1]
        kept[hit[0]] = (hit[0], hit[1], {"speaker": " ".join(line["speaker"].split()),
                                         "delivery": " ".join(line["delivery"].split()),
                                         "text": doc.words(hit[0], hit[1], _LINE_END)})
    lines: list[tuple[int, int, dict[str, str]]] = []
    for at in sorted(kept):
        if not lines or at >= lines[-1][1]:  # a quote inside the line before it is the same words twice
            lines.append(kept[at])
    return lines, len(spoken) - len(lines)


def _cut_out(doc: Doc, s0: int, s1: int, quotes: list[str], keep: list[tuple[int, int]]) -> str:
    """The source between s0 and s1 without the text the reader marked as not story, wherever it repeats. A quote that
    would cut into a spoken line (`keep`, folded ranges) is not used."""
    k0, k1 = doc.key_at(s0), doc.key_at(s1)
    cuts: list[tuple[int, int]] = []
    for quote in quotes:
        if len(fold(quote)) < MIN_IGNORE:
            continue
        at = k0
        while hit := doc.find(quote, at, k1):
            at = hit[1]
            if not any(hit[0] < b and a < hit[1] for a, b in keep):
                cuts.append(doc.span(*hit))
    out, pos = [], s0
    for a, b in sorted(cuts):
        if a >= pos:
            out.append(doc.src[pos:a])
            pos = b
    out.append(doc.src[pos:s1])
    return "".join(out).strip()


def check(raw: dict[str, Any], text: str, *, limit: int | None = None) -> dict[str, Any]:
    """The reader's `Output` (as a dict) against the document -> the reading that is saved (`story.json`)."""
    doc = Doc(text)
    warnings: list[str] = []
    if limit is not None and len(text) > limit:
        warnings.append(f"Only the first {limit:,} characters of this document were read.")
    asked = list(raw.get("episodes") or [])
    slices = _slices(doc, asked, warnings)
    episodes: list[dict[str, Any]] = []
    lost_lines = 0
    ignore = list(raw.get("ignore") or [])
    for k0, k1, ep in slices:
        found, lost = _lines(doc, k0, k1, ep["spoken"])
        lost_lines += lost
        s0, s1 = doc.span(k0, k1, _EPISODE_END)
        keep = [(a, b) for a, b, _ in found]
        # The text before the first line, between two lines and after the last: what is seen, not said.
        edges = [s0]
        for a, b, _ in found:
            edges += doc.span(a, b, _LINE_END)
        edges.append(s1)
        gaps = [_cut_out(doc, edges[i], edges[i + 1], ignore, keep).strip(_QUOTES) for i in range(0, len(edges), 2)]
        episodes.append({"number": ep["number"], "title": " ".join(ep["title"].split()), "kind": ep["kind"],
                         "duration_s": ep["duration_s"], "body": _cut_out(doc, s0, s1, ignore, keep),
                         "spoken": [line for _, _, line in found], "gaps": gaps})
    if lost_lines:
        warnings.append(f"{_plural(lost_lines, 'spoken line')} the reader quoted {'is' if lost_lines == 1 else 'are'} "
                        "not in the document; left out.")
    people, seen = [], set()
    for p in raw.get("people") or []:
        shown = any(doc.find(q) for q in [p["evidence"], p["name"], *p["aliases"]] if q.strip())
        if shown and p["name"].strip().casefold() not in seen:
            seen.add(p["name"].strip().casefold())
            people.append({"name": " ".join(p["name"].split()), "aliases": [a for a in p["aliases"] if a.strip()],
                           "voice_only": bool(p["voice_only"])})
    lost_people = len(raw.get("people") or []) - len(people)
    return {"version": VERSION, "sha": text_sha(text), "contains": list(raw.get("contains") or []),
            "episodes": episodes, "people": people,
            "ignore": [q for q in raw.get("ignore") or [] if doc.find(q)],
            "dropped": {"episodes": len(asked) - len(episodes), "lines": lost_lines, "people": lost_people},
            "warnings": warnings}
