"""The two memories of one production (plan/2026-11-11 §5).

The split reads each document on its own (one call per document, its own numbered lines). Code then lays the documents
one after the other into ONE numbered text, so every pointer in the breakdown memory is a line of that text: `shift`
moves a document's split by its offset, `merge` joins the splits (a second card for the same person, place or thing is
folded into the first, and a fact the two documents state differently becomes a creation question, §4.2), and `doc`
rebuilds the text from the source memories plus the lines of scenes a person edited (`Breakdown.person_lines`).

Pure: no model, no database.
"""

from __future__ import annotations

import re
from typing import Any

from contracts.breakdown.lines import Doc, Span
from contracts.breakdown.schema import (
    Breakdown,
    CardW,
    DocPart,
    EpisodeCutW,
    FieldW,
    RangeW,
    RuleW,
    SceneCutW,
    SectionW,
    SourceMemory,
    SpanW,
    SplitW,
)

PAGE_FURNITURE = re.compile(r"^\s*\d{1,3}\s*$")


def clean_lines(text: str) -> list[str]:
    """The document's text as lines: form feeds removed (the PDF text layer's page breaks, §4.1), `\\r` dropped."""
    return [ln.rstrip("\r").replace("\x0c", "") for ln in text.split("\n")]


def strip_furniture(lines: list[str]) -> list[str]:
    """Remove a running header repeated on every page: a block of lines that recurs at least three times followed by a
    page number. Conservative: only an exact repeat of the same 1-3 lines with a page number is taken out."""
    counts: dict[tuple[str, ...], int] = {}
    for i in range(len(lines)):
        for n in (1, 2, 3):
            if i + n < len(lines) and PAGE_FURNITURE.match(lines[i + n]) and all(x.strip() for x in lines[i : i + n]):
                key = tuple(lines[i : i + n])
                counts[key] = counts.get(key, 0) + 1
    heads = sorted((k for k, c in counts.items() if c >= 3), key=len, reverse=True)
    if not heads:
        return lines
    out: list[str] = []
    i = 0
    while i < len(lines):
        for h in heads:
            n = len(h)
            if tuple(lines[i : i + n]) == h and i + n < len(lines) and PAGE_FURNITURE.match(lines[i + n]):
                i += n + 1
                break
        else:
            out.append(lines[i])
            i += 1
    return out


def _span(s: SpanW, off: int) -> SpanW:
    return SpanW(line=s.line + off, w_from=s.w_from, w_to=s.w_to)


def _range(r: RangeW, off: int) -> RangeW:
    return RangeW(start=r.start + off, end=r.end + off)


def shift(split: SplitW, line_off: int, card_off: int) -> SplitW:
    """The same split with every line moved by `line_off` and every card index by `card_off`."""
    return SplitW(
        sections=[SectionW(label=s.label, lines=_range(s.lines, line_off), note=s.note) for s in split.sections],
        cards=[
            CardW(
                kind=c.kind,
                name=_span(c.name, line_off),
                lines=_range(c.lines, line_off),
                fields=[FieldW(name=f.name, span=_span(f.span, line_off)) for f in c.fields],
                place_kind=c.place_kind,
                seen=c.seen,
                within=c.within + card_off if c.within >= 0 else -1,
            )
            for c in split.cards
        ],
        rules=[
            RuleW(
                about=r.about,
                lines=_range(r.lines, line_off),
                scope_kind=r.scope_kind,
                scope_card=r.scope_card + card_off if r.scope_card >= 0 else -1,
                scope_number=r.scope_number,
            )
            for r in split.rules
        ],
        episodes=[
            EpisodeCutW(
                number=e.number,
                heading=e.heading + line_off,
                scenes=[
                    SceneCutW(number=s.number, heading=s.heading + line_off, last=s.last + line_off) for s in e.scenes
                ],
            )
            for e in split.episodes
        ],
    )


def doc(sources: list[SourceMemory], person_lines: list[str] | None = None) -> Doc:
    """The production's one numbered text: each document's lines in order, then the lines a person wrote."""
    lines: list[str] = []
    for s in sources:
        lines += s.lines
    return Doc(lines + list(person_lines or []))


def parts(sources: list[SourceMemory]) -> list[DocPart]:
    out, at = [], 0
    for s in sources:
        out.append(DocPart(document_id=s.document_id, filename=s.filename, first=at + 1, last=at + len(s.lines)))
        at += len(s.lines)
    return out


def _name(d: Doc, s: SpanW) -> str:
    sp = Span(s.line, s.w_from, s.w_to)
    return d.text([sp]).strip(" .,:;-").lower() if d.span_ok(sp) else ""


def merge(sources: list[SourceMemory]) -> tuple[SplitW, Doc, list[str]]:
    """One split over the combined text, and the creation questions the merge raises.

    The same person, place or thing named on two documents' cards (a bible and a script) is ONE card: the first
    document's card stays, the later card's facts fill only the fields the first lacks, and a field both state
    differently is a question for a person (never resolved by code). Episodes and scenes are taken from every document
    that has them; a scene number two documents both cut is a question too (the first document's cut is kept)."""
    d = doc(sources)
    cards: list[CardW] = []
    rules: list[RuleW] = []
    sections: list[SectionW] = []
    episodes: dict[int, EpisodeCutW] = {}
    questions: list[str] = []
    by_name: dict[tuple[str, str], int] = {}
    line_off = 0
    for src in sources:
        sp = shift(src.split, line_off, 0)
        line_off += len(src.lines)
        index: dict[int, int] = {}  # this document's card index -> index in the merged list
        for i, c in enumerate(sp.cards):
            key = (c.kind, _name(d, c.name))
            if key[1] and key in by_name:
                j = by_name[key]
                index[i] = j
                have = {f.name: f for f in cards[j].fields}
                for f in c.fields:
                    if f.name not in have:
                        cards[j].fields.append(f)
                    elif d.text([Span(f.span.line, f.span.w_from, f.span.w_to)]) != d.text(
                        [Span(have[f.name].span.line, have[f.name].span.w_from, have[f.name].span.w_to)]
                    ):
                        questions.append(
                            f"{key[1].title()}: {src.filename} gives a different {f.name} from an earlier "
                            "document. The earlier one is used; which is right?"
                        )
                continue
            index[i] = len(cards)
            if key[1]:
                by_name[key] = len(cards)
            cards.append(c)
        for i, c in enumerate(sp.cards):  # `within` is an index into this document's own list: re-point it
            if index[i] >= len(cards) or cards[index[i]] is not c:
                continue
            if c.within >= 0:
                c.within = index.get(c.within, -1)
        for r in sp.rules:
            if r.scope_card >= 0:
                r.scope_card = index.get(r.scope_card, -1)
            rules.append(r)
        sections += sp.sections
        for e in sp.episodes:
            got = episodes.setdefault(e.number, EpisodeCutW(number=e.number, heading=e.heading, scenes=[]))
            numbers = {s.number for s in got.scenes}
            for s in e.scenes:
                if s.number in numbers:
                    questions.append(
                        f"Episode {e.number or 1}, scene {s.number}: {src.filename} also has this scene. "
                        "The first document's scene is used; is that right?"
                    )
                    continue
                got.scenes.append(s)
    eps = [episodes[k] for k in sorted(episodes)]
    return SplitW(sections=sections, cards=cards, rules=rules, episodes=eps), d, questions


def stamp(bd: Breakdown, sources: list[SourceMemory], questions: list[str]) -> Breakdown:
    """The product's fields on a freshly built memory: where each document sits, and the merge's questions."""
    bd.documents = parts(sources)
    bd.questions = [*bd.questions, *questions]
    return bd


def blocks_as_lines(blocks: list[dict[str, Any]], names: dict[str, str]) -> list[str]:
    """A person's edited scene as numbered lines for the one-scene episode call: a heading line, then one line per
    block, a dialogue block written `NAME - words` (the cue the episode prompt knows)."""
    out = []
    for b in blocks:
        text = " ".join(str(b.get("text") or "").split())
        if not text:
            continue
        if b.get("kind") == "dialogue" and b.get("speaker"):
            out.append(f"{names.get(str(b['speaker']), str(b['speaker'])).upper()} - {text}")
        else:
            out.append(text)
    return out
