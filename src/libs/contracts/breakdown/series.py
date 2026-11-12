"""What the drama IS: its genre, tone, world, theme and premise (plan/2026-11-12b).

The `breakdown_series` agent reads the parts of the documents that can say it (title pages, overviews, notes) and JUDGES
what each line means: which genre facets are the drama's main ones, what the tone asks for, what is not the drama's
identity at all (a running time, a story clue, a document label, a direction for the camera) and goes to `left_out`.
Code then checks every value (`check`): the quote is in its lines, `says` holds no number and no gated word, a facet is
in its quote. What passes is stored on the breakdown memory (`Breakdown.series`) and from there goes:

- into every scene packet as `J_series` (`packet_part`), rendered first inside Raphael's `<packet>` (`render_lines`);
- into `production_memory` as `series` facts (`memory_rows`), so the subscribed agents are given it and a person can
  edit or reject it in the memory panel;
- into the first-frame and video prompts as a short genre phrase (`contracts.memory.genre_of` reads it back from those
  rows, so a person's edit reaches every prompt).

Pure: no model, no database.
"""

from __future__ import annotations

import re
from typing import Any

from contracts import safe_depiction
from contracts.breakdown.lines import Doc
from contracts.breakdown.schema import Breakdown, Finding, SeriesW, SourceMemory

FIELDS = ("genre", "tone", "world", "theme", "premise")
LABELS = ("title_page", "overview", "other")  # the split's sections that can say what the drama is
HEAD_LINES = 60  # every document's first lines are sent too: a title page the split did not label
FALLBACK_LINES = 200  # a document with no such section sends its first lines
MAX_LINES = 600  # the whole message, across documents
EMPTY = "empty"
TOPIC = "series"
MAX_FACETS = 2  # in a picture prompt: "action and crime thriller"
MAX_PHRASE = 60
_NUMBERS = re.compile(r"\d|\b(minutes?|seconds?|hours?|episodes?|runtime|running time)\b", re.IGNORECASE)
HEADING = "SERIES (what this drama is; play every scene as part of it)"


def _norm(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def _wanted(s: SourceMemory) -> list[int]:
    """The 1-based line numbers of one document that are sent: its labelled identity sections and its first lines."""
    n = len(s.lines)
    picked: set[int] = set(range(1, min(n, HEAD_LINES) + 1))
    labelled = [x for x in s.split.sections if x.label in LABELS]
    for x in labelled:
        picked.update(range(max(1, x.lines.start), min(n, x.lines.end) + 1))
    if not labelled:
        picked.update(range(1, min(n, FALLBACK_LINES) + 1))
    return sorted(picked)


def message(sources: list[SourceMemory]) -> str:
    """The reader's message: each document's chosen lines, numbered as the production's ONE text numbers them
    (`memory.doc`), so every pointer the reader gives is a breakdown line. A gap is shown as `...`. Documents are data
    inside labelled tags."""
    out: list[str] = []
    at, total = 0, 0
    for s in sources:
        wanted = _wanted(s)[: max(0, MAX_LINES - total)]
        total += len(wanted)
        if wanted:
            body, last = [], 0
            for i in wanted:
                if last and i != last + 1:
                    body.append("...")
                body.append(f"{at + i}: {s.lines[i - 1]}")
                last = i
            out.append(f'<document filename="{s.filename}">\n' + "\n".join(body) + "\n</document>")
        at += len(s.lines)
    return "\n\n".join(out)


def _empty(why: str) -> dict[str, str]:
    return {EMPTY: why}


def check(answer: SeriesW, d: Doc, bd: Breakdown) -> tuple[dict[str, Any], list[Finding]]:
    """Code's checks on the reader's answer -> (the block that is stored, the findings for what was dropped).

    A field is kept only when its quote lies in its lines (spacing and case aside), its `says` holds no digit and no
    duration or count word, and its `says` passes the safe-depiction gate. A genre facet is kept only when its words are
    in the genre's quote. A world place is matched to a place card by name; one with no card keeps no id."""
    findings: list[Finding] = []
    out: dict[str, Any] = {}
    places = {_norm(e.name): e.id for e in bd.entities if e.kind == "place"}

    def drop(key: str, why: str) -> None:
        findings.append(Finding(code=TOPIC, message=f"Series {key}: {why}; left out"))
        out[key] = _empty(why)

    for key in FIELDS:
        f = getattr(answer, key)
        if not f.found:
            out[key] = _empty("not stated")
            continue
        lo, hi = f.lines.start, f.lines.end
        span = _norm(d.cut(lo, hi)) if d.has_line(lo) and d.has_line(hi) and lo <= hi else ""
        says = " ".join(f.says.split())
        if not f.quote.strip() or _norm(f.quote) not in span:
            drop(key, f"the quote is not in lines {lo}-{hi}")
            continue
        if not says:
            drop(key, "no words of its own")
            continue
        if _NUMBERS.search(says):
            drop(key, f"its words hold a number or a length ({says!r})")
            continue
        gated = safe_depiction.blocking(says)
        if gated:
            drop(key, f"its words hold a gated word ({', '.join(g.word for g in gated)})")
            continue
        item: dict[str, Any] = {"says": says, "quote": " ".join(f.quote.split()), "lines": [lo, hi],
                                "source": "script"}
        if key == "genre":
            kept = []
            for fc in answer.genre.facets:
                name = " ".join(fc.name.split()).casefold()
                if name and all(w in _norm(f.quote) for w in name.split()) and not _NUMBERS.search(name):
                    kept.append({"name": name, "weight": fc.weight})
                else:
                    findings.append(Finding(code=TOPIC, message=f"Series genre: facet {fc.name!r} is not in its "
                                                                  "quote; left out"))
            if not kept:
                drop(key, "no facet is in its quote")
                continue
            item["facets"] = kept
        elif key == "world":
            item["places"] = [{"name": " ".join(p.split()), "id": places.get(_norm(p), "")}
                              for p in answer.world.places if p.strip()]
            for p in item["places"]:
                if not p["id"]:
                    findings.append(Finding(code=TOPIC, message=f"Series world: {p['name']!r} matches no place card"))
        elif key == "theme":
            item["language"] = answer.theme.language.strip()
        elif key == "premise":
            item["planner_only"] = bool(safe_depiction.blocking(item["quote"]))
        out[key] = item
    out["left_out"] = [{"quote": " ".join(x.quote.split()), "lines": [x.lines.start, x.lines.end],
                        "why": " ".join(x.why.split())} for x in answer.left_out]
    return out, findings


def facets(block: dict[str, Any] | None, weight: str = "main") -> list[str]:
    g = (block or {}).get("genre") or {}
    return [f["name"] for f in g.get("facets") or [] if f.get("weight") == weight]


def phrase(names: list[str]) -> str:
    """At most MAX_FACETS facets as a phrase a picture prompt can carry ("action and crime thriller"); "" when a facet
    holds a number or a gated word, or the phrase is too long."""
    picked = [" ".join(n.split()) for n in names if n.strip()][:MAX_FACETS]
    text = " and ".join(picked)
    if not text or len(text) > MAX_PHRASE or _NUMBERS.search(text) or safe_depiction.blocking(text):
        return ""
    return text


def genre_line(block: dict[str, Any] | None) -> str:
    """The genre row's words: `Genre: <main facets>; <thread facets> as a thread. <the reader's sentence>`.
    `contracts.memory.genre_of` reads the part before the first `;` or `.` back (a person may type just "family
    drama")."""
    g = (block or {}).get("genre") or {}
    main, thread = facets(block), facets(block, "thread")
    if not main:
        return ""
    head = "Genre: " + ", ".join(main) + (f"; {', '.join(thread)} as a thread" if thread else "")
    return f"{head}. {g['says']}" if g.get("says") else f"{head}."


def memory_rows(bd: Breakdown) -> dict[str, list[dict[str, Any]]]:
    """Each kept field as a `production_memory` fact (topic `series`, the whole production), grouped by the document its
    lines are in. A premise whose quote has a gated word is for planners only and is not written."""
    block = bd.series or {}
    rows: dict[str, list[dict[str, Any]]] = {}
    for key in FIELDS:
        v = block.get(key) or {}
        if "says" not in v or (key == "premise" and v.get("planner_only")):
            continue
        says = genre_line(block) if key == "genre" else f"{key.title()}: {v['says']}"
        doc = next((x.document_id for x in bd.documents if x.first <= v["lines"][0] <= x.last), "")
        if says and doc:
            rows.setdefault(doc, []).append({"topic": TOPIC, "applies_to": "production", "says": says[:2000],
                                             "quote": v["quote"][:2000], "strength": "fact"})
    return rows


def packet_part(bd: Breakdown, packet: dict[str, Any]) -> dict[str, Any] | None:
    """`J_series` of one scene's packet: the production's block (without `left_out`) and where this scene sits in it.
    None when the breakdown has no series block."""
    if not bd.series:
        return None
    part = {k: bd.series.get(k) or _empty("not stated") for k in FIELDS}
    place_id = str((packet.get("C_place") or {}).get("id") or "")
    place = bd.entity(place_id) if place_id else None
    region = bd.entity(place.within) if place is not None and place.within else None
    feeling = packet.get("F_feeling") or {}
    part["this_scene"] = {
        "place": place_id,
        "place_name": place.name if place is not None else "",
        "region": region.id if region is not None else "",
        "region_name": region.name if region is not None else "",
        "scoped_rules": [r["id"] for r in packet.get("G_direction") or [] if r.get("applies") == "scoped"],
        "mood": feeling.get("mood") if isinstance(feeling.get("mood"), list) else [],
    }
    return part


def render_lines(part: dict[str, Any] | None) -> list[str]:
    """`J_series` as the planner reads it, first inside `<packet>`. Nothing when the packet has none."""
    if not part:
        return []
    out = [HEADING]
    g = part.get("genre") or {}
    if g.get("facets"):
        out.append("Genre: " + ", ".join(f"{f['name']} ({f['weight']})" for f in g["facets"])
                   + (f". {g['says']}" if g.get("says") else ""))
    for key in ("tone", "world", "theme", "premise"):
        v = part.get(key) or {}
        if "says" not in v:
            continue
        line = f"{key.title()}: {v['says']}"
        if key == "world" and v.get("places"):
            line += " Places: " + ", ".join(f"{p['name']} [{p['id']}]" if p.get("id") else p["name"]
                                             for p in v["places"])
        out.append(line)
    t = part.get("this_scene") or {}
    where = ""
    if t.get("place"):
        where = f"{t.get('place_name') or t['place']} [{t['place']}]"
        if t.get("region"):
            where += f" in {t.get('region_name') or t['region']} [{t['region']}]"
    bits = [f"place {where}" if where else "",
            f"scoped direction {', '.join(t['scoped_rules'])}" if t.get("scoped_rules") else "",
            f"mood {', '.join(t['mood'])}" if t.get("mood") else ""]
    if any(bits):
        out.append("This scene: " + "; ".join(b for b in bits if b) + ".")
    return out if len(out) > 1 else []
