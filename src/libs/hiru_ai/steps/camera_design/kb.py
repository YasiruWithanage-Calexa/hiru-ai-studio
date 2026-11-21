"""The cinematography knowledge base as the Camera agent's toolbox (plan/2026-11-20c D8), ported from
`lab/camera_agent/kb.py`:

    menu()                   the <moves> part: one line per catalogue move with what it does and when to use it, from
                             the base's CSVs (629 terms) through the catalogue's mapping (`contracts.camera`)
    fits(clip)               the moves that can fit a clip: no fast move on a speaking face, aerials only on an exterior
                             master or exit, nothing longer than the take
    ideas(rows, fit)         the base's embedding search results for one clip (`craft_techniques` rows, k=4) -> moves
                             that fit, each with its effect and use

Absent-safe: no search (no key, no index) -> no ideas; the menu still goes. The lab's keyword ideas were noisy (the
"dialogue" tag pointed at a crab shot), so the product asks the embedding search (`TechniqueRetriever` / the `search`
port's `techniques`), not keywords.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import Any

from contracts import camera as cam

Row = dict[str, Any]
SRC = Path(__file__).resolve().parents[2] / "knowledge_bases" / "cinematography" / "sources"


def _read(name: str) -> list[dict[str, str]]:
    with (SRC / name).open(encoding="utf-8", newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


@cache
def terms() -> dict[str, dict[str, str]]:
    """term slug -> its row (effect, use_case ...). {} when the base's files are not there."""
    try:
        return {t["term_slug"]: t for t in _read("cine_terms.csv")}
    except OSError:
        return {}


def _line(effect: str, use: str) -> str:
    return f"{effect.rstrip('.')}. Use: {use.rstrip('.')}."


@cache
def menu() -> str:
    """One line per move: what it does to the viewer and when to use it (from the base, or the catalogue's `OWN`)."""
    out = ["<moves>", "Your whole toolbox, from Hiru's cinematography knowledge base. Consider all of it, pick what "
           "the moment needs. Format: move: what it does. Use: when."]
    for m in cam.MOVES:
        term = terms().get(m.term)
        if term:
            v = f" ({cam.VARIANT[m.slug]})" if m.slug in cam.VARIANT else ""
            out.append(f"- {m.slug}{v}: {_line(term['effect'], term['use_case'])}")
        elif m.slug in cam.OWN:
            out.append(f"- {m.slug}: {cam.OWN[m.slug]}")
        else:
            out.append(f"- {m.slug}")
    out.append("Focus:")
    for f, slug in cam.FOCUS_TERM.items():
        t = terms().get(slug)
        if t:
            out.append(f"- {f}: {_line(t['effect'], t['use_case'])}")
    out.append("</moves>")
    return "\n".join(out)


def fits(clip: Mapping[str, Any]) -> list[str]:
    """The moves that can fit the clip (an idea that cannot fit is noise)."""
    speaks = bool(clip.get("speaks"))
    wide_ok = bool(clip.get("exterior")) and clip.get("role") in ("master", "establishing", "clean_exit")
    take = float(clip.get("take_s") or 0)
    return [m.slug for m in cam.MOVES
            if not (speaks and m.fast) and (m.slug not in cam.AERIAL or wide_ok) and m.min_s <= take]


def query(clip: Mapping[str, Any]) -> str:
    """What the clip is for, as the search reads it: the planner's why and summary, the intent and delivery of what is
    said, the scene's mood."""
    return " ".join(str(clip.get(k) or "") for k in ("why", "summary", "said", "mood")).strip()


def ideas(rows: Iterable[Mapping[str, Any]], fit: Iterable[str], k: int = 4) -> list[tuple[str, str]]:
    """The search's rows for one clip -> (move, what it does; use) for the moves that fit, at most k, in the search's
    order. A term several moves share (pan) offers its fitting moves together; `hold` is never an idea (the agent has
    it anyway, and the static term lists "Dialogue scenes" first)."""
    fitting = list(fit)
    out: list[tuple[str, str]] = []
    for r in rows:
        slug = str(r.get("slug") or "")
        moves = [m for m in fitting if cam.MOVE[m].term == slug and m != "hold"]
        if not moves:
            continue
        effect = str(r.get("effect") or r.get("definition") or "").rstrip(".")
        use = str(r.get("use_case") or "").rstrip(".")
        out.append((" / ".join(moves), f"{effect}; use: {use}" if use else effect))
        if len(out) >= k:
            break
    return out
