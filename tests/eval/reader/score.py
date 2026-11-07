"""How well a reading matches the gold (plan/2026-11-06f §5). Pure code; used by `scripts/eval_reader.py` and its tests.

Both sides are compared in the parser's shape (`ParsedDocument`), so the rules (today's baseline) and the reader are
scored the same way. Scores are shares in [0, 1]:

  scenes        1 when the scene count is the gold's, else the smaller count over the larger
  headings      int/ext, location, length and flashback equal, over the scenes paired in order
  time_of_day   the time of day equal, over the paired scenes
  dialogue      gold lines found (same words, normalised), over the gold's lines
  speakers      found lines whose speaker is the gold's person (a name or an alias of the gold's), over the found
  words         1 - character error rate of all the dialogue, in order (Sinhala is compared letter by letter)
  canon         the gold's people, places and things found by name or alias, over the gold's
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from contracts.canon import name_key
from contracts.doc_read import normalise
from contracts.screenplay import ParsedDocument

SCORES = ("scenes", "headings", "time_of_day", "dialogue", "speakers", "words", "canon")


def _lines(doc: ParsedDocument) -> list[tuple[str, str]]:
    return [(b.speaker, normalise(b.text)) for s in doc.scenes for b in s.blocks if b.kind == "dialogue"]


def _ratio(a: int, b: int) -> float:
    return 1.0 if a == b else min(a, b) / max(a, b) if max(a, b) else 1.0


def score(gold: ParsedDocument, got: ParsedDocument, *, aliases: dict[str, set[str]] | None = None,
          gold_canon: list[str] | None = None, got_canon: list[str] | None = None) -> dict[str, float]:
    """`aliases`: name_key of a gold person -> every name_key they go by (their cues). `gold_canon` / `got_canon`: the
    names (and aliases) each side's canon holds."""
    out: dict[str, float] = {"scenes": _ratio(len(gold.scenes), len(got.scenes))}
    pairs = list(zip(gold.scenes, got.scenes, strict=False))
    if pairs:
        same = [(g.heading.int_ext == r.heading.int_ext, name_key(g.heading.location) == name_key(r.heading.location),
                 g.heading.stated_seconds == r.heading.stated_seconds, g.heading.flashback == r.heading.flashback)
                for g, r in pairs]
        out["headings"] = sum(sum(s) for s in same) / (4 * len(same))
        out["time_of_day"] = sum(g.heading.time_of_day.casefold() == r.heading.time_of_day.casefold()
                                 for g, r in pairs) / len(pairs)
    else:
        out["headings"] = out["time_of_day"] = 0.0
    want, have = _lines(gold), _lines(got)
    pool = list(have)
    found: list[tuple[str, str]] = []
    for speaker, words in want:
        hit = next((h for h in pool if h[1] == words), None)
        if hit is not None:
            pool.remove(hit)
            found.append((speaker, hit[0]))
    out["dialogue"] = len(found) / len(want) if want else 1.0
    known = aliases or {}
    out["speakers"] = (sum(1 for g, r in found if name_key(r) in known.get(name_key(g), {name_key(g)}))
                       / len(found)) if found else 0.0
    a, b = " ".join(w for _, w in want), " ".join(w for _, w in have)
    out["words"] = SequenceMatcher(None, a, b, autojunk=False).ratio() if a or b else 1.0
    if gold_canon is not None:
        have_names = {name_key(n) for n in got_canon or []}
        hits = sum(1 for n in gold_canon if name_key(n) in have_names)
        out["canon"] = hits / len(gold_canon) if gold_canon else 1.0
    return out


def table(rows: dict[str, dict[str, float]]) -> str:
    """A markdown table: one row per arm (rules, reader ...), one column per score."""
    head = "| arm | " + " | ".join(SCORES) + " |\n|---|" + "---|" * len(SCORES)
    body = ["| " + arm + " | " + " | ".join(f"{s[k]:.2f}" if k in s else "" for k in SCORES) + " |"
            for arm, s in rows.items()]
    return "\n".join([head, *body])


def gold_names(answer: dict[str, Any]) -> tuple[list[str], dict[str, set[str]]]:
    """The gold canon's names, and each person's every name (for the speaker score)."""
    names: list[str] = []
    aliases: dict[str, set[str]] = {}
    for field in ("characters", "locations", "props"):
        for e in answer["canon"][field]:
            names.append(e["name"])
            if field == "characters":
                aliases[name_key(e["name"])] = {name_key(e["name"]), *(name_key(a) for a in e["aliases"])}
    return names, aliases
