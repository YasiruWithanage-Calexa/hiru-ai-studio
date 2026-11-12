"""Today's columns, filled from the breakdown memory by code (plan/2026-11-11 decision D1, phase 3).

The breakdown memory is the ONE source. At the end of creation, and after each refinement, code writes from it:

- `structure(bd)`        the resolved structure `structure_write` already turns into `episodes`, `scenes` (heading,
title,
                         script blocks, envelope) and `dialogue_lines` (each spoken line verbatim, its speaker, its
                         delivery)
- `canon_cards(bd)`      every person, place and thing as a canon card (name, kind, the card facts the documents give)
- `memory_rows(bd)`      each direction rule as a `production_memory` entry (quote = the document's words), and what
                         the drama is as `series` facts (plan/2026-11-12b)
- `staging(bd, scene)`   the stager's map in `scenes.staging`'s shape
- `line_map(scene, rows)` which `dialogue_lines` row each dialogue block became (so Raphael's line ids are real rows)

Pure: no model, no database. Nothing here re-types a word: every text is the memory's, which code cut from a document.
"""

from __future__ import annotations

import re
from typing import Any

from contracts.breakdown import series
from contracts.breakdown.packet import _pretty
from contracts.breakdown.schema import Breakdown, Scene
from contracts.screenplay import parse_heading

# the packet's presence -> the delivery today's line carries (Raphael's `is_heard` reads these words)
DELIVERY = {
    "phone": "on the phone",
    "voice_message": "voice message",
    "recording": "recording",
    "voice_over": "voice over",
    "thought": "voice over",
}
KIND = {"action": "action", "text": "action", "sound": "sound", "transition": "cut"}
CANON_KIND = {"person": "character", "place": "location", "thing": "prop"}
# the card facts a canon card has a field for (contracts.canon.CanonCard); the rest go to its notes
CARD_FIELDS = {
    "person": ("age", "gender", "appearance", "wardrobe", "voice"),
    "place": ("look",),
    "thing": ("details",),
}
CARD_LIMITS = {
    "summary": 2000,
    "age": 60,
    "gender": 40,
    "appearance": 600,
    "wardrobe": 600,
    "voice": 300,
    "look": 800,
    "details": 800,
    "notes": 2000,
}
_MINUTES = re.compile(r"(\d+(?:\.\d+)?)\s*MINUTES?\s*$", re.IGNORECASE)


def _name(bd: Breakdown, id_: str) -> str:
    e = bd.entity(id_)
    return _pretty(e.name) if e else ""


def scene_blocks(bd: Breakdown, sc: Scene) -> list[dict[str, Any]]:
    """The scene's blocks in `structure_write`'s shape, one per memory block (so block i is script block i)."""
    out: list[dict[str, Any]] = []
    for b in sc.blocks:
        text = str(b.get("text") or "")
        if b["kind"] == "dialogue" and b.get("speaker"):
            name = _name(bd, b["speaker"]) or str(b["speaker"])
            out.append(
                {
                    "kind": "dialogue",
                    "speaker": name,
                    "character": {"new": name},
                    "text": text,
                    "delivery": DELIVERY.get(b.get("presence", ""), ""),
                }
            )
        else:
            out.append({"kind": KIND.get(b["kind"], "action"), "text": text})
    return out


def envelope_of(sc: Scene) -> int | None:
    m = _MINUTES.search(sc.heading)
    return max(4, round(float(m.group(1)) * 60)) if m else None


def structure(bd: Breakdown, *, doc_ids: list[str] | None = None) -> dict[str, Any]:
    """The resolved structure for `structure_write`: titles and synopses from the memory, scenes with briefs only (a
    scene the episode call could not break down is left as the store has it)."""
    synopses = {int(s["episode"]): s["text"] for s in (bd.continuity or {}).get("synopses", [])}
    eps: dict[int, dict[str, Any]] = {}
    for sc in bd.scenes:
        ep = eps.setdefault(
            sc.episode,
            {
                "number": sc.episode,
                "title": "",
                "synopsis": synopses.get(sc.episode, ""),
                "doc_ids": list(doc_ids or [d.document_id for d in bd.documents]),
                "scenes": [],
            },
        )
        if sc.brief is None:
            continue
        heading = parse_heading(sc.heading)
        place = _name(bd, sc.brief.get("place", ""))
        row: dict[str, Any] = {
            "number": sc.number,
            "title": str(sc.brief.get("title") or "")[:120],
            "heading": {"raw": sc.heading, "time_of_day": heading.time_of_day},
            "location": {"new": place} if place else None,
            "blocks": scene_blocks(bd, sc),
        }
        if (env := envelope_of(sc)) is not None:
            row["envelope_s"] = env
        ep["scenes"].append(row)
    return {"episodes": [eps[k] for k in sorted(eps)]}


def canon_cards(bd: Breakdown) -> list[dict[str, Any]]:
    """Every entity as a canon card: `{kind, name, card}` (the card's keys are `contracts.canon.CanonCard` fields)."""
    out = []
    for e in bd.entities:
        card: dict[str, str] = {}
        notes: list[str] = []
        for k, v in e.card.items():
            text = " ".join(str(v.value).split())
            if not text:
                continue
            if k == "summary":
                card["summary"] = text
            elif k in CARD_FIELDS[e.kind]:
                card[k] = text
            elif k == "look" and e.kind == "person":
                card["appearance"] = (card.get("appearance", "") + " " + text).strip()
            else:
                notes.append(f"{k}: {text}")
        if notes:
            card["notes"] = "; ".join(notes)
        out.append(
            {
                "id": e.id,
                "kind": CANON_KIND[e.kind],
                "name": _pretty(e.name),
                "card": {k: v[: CARD_LIMITS[k]] for k, v in card.items()},
                # plan/2026-11-12: a thing the script implies but does not name; its canon version says `inferred`
                "inferred": bool(e.card.get("summary")) and e.card["summary"].source == "inferred",
            }
        )
    return out


def _document_of(bd: Breakdown, line: int) -> str:
    return next((d.document_id for d in bd.documents if d.first <= line <= d.last), "")


def memory_rows(bd: Breakdown) -> dict[str, list[dict[str, Any]]]:
    """Each direction rule as a `production_memory` entry, grouped by the document it was read from (the store's
    `replace_from` replaces one document's drafts and keeps what a person approved, rejected or edited)."""
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for r in bd.rules:
        text = " ".join(r.text.split())[:2000]
        if not text:
            continue
        if r.scope_kind == "place":
            applies = f"place:{_name(bd, r.scope_id)}" if _name(bd, r.scope_id) else "production"
        elif r.scope_kind == "episode" and r.scope_id.isdigit() and int(r.scope_id) > 0:
            applies = f"episode:{int(r.scope_id)}"
        elif r.scope_kind == "scene" and r.scope_id:
            applies = f"when:in scene {r.scope_id}"
        else:
            applies = "production"
        doc = _document_of(bd, r.lines[0])
        if doc:
            by_doc.setdefault(doc, []).append(
                {
                    "topic": r.about.replace("_", " ")[:40],
                    "applies_to": applies,
                    "says": text,
                    "quote": text,
                    "strength": "prefer",
                }
            )
    for doc, rows in series.memory_rows(bd).items():  # plan/2026-11-12b: what the drama is, as `series` facts
        by_doc.setdefault(doc, []).extend(rows)
    return by_doc


def staging(bd: Breakdown, sc: Scene, *, script_version: int = 0, basis: str = "") -> dict[str, Any] | None:
    """The stager's map in `contracts.stagemap.SceneStaging`'s shape (`who` is the person's name, `block` the index of
    the script block, which is the memory block of the same index)."""
    if not sc.stage:
        return None
    marks = []
    for m in sc.stage["marks"]:
        marks.append(
            {
                "block": m["block"],
                "who": _name(bd, m["person"]) or m["person"],
                "zone": m["zone"],
                **{
                    k: m[k]
                    for k in (
                        "facing",
                        "frame_side",
                        "holding",
                        "posture",
                        "left_hand",
                        "right_hand",
                        "condition",
                        "wearing",
                    )
                },
            }
        )
    return {
        "zones": list(sc.stage["zones"]),
        "marks": marks,
        "props": [
            {"block": p["block"], "prop": p["prop"], "where": p["where"], "state": p["state"]}
            for p in sc.stage["props"]
        ],
        "by": "model",
        "for_version": script_version,
        "basis": basis,
    }


def line_map(sc: Scene, lines: list[dict[str, Any]]) -> dict[str, str]:
    """Dialogue block id -> its `dialogue_lines` row id: the scene's dialogue blocks in order against its lines by `ord`
    (`structure_write` writes one line per dialogue block, in block order)."""
    spoken = [b["id"] for b in sc.blocks if b["kind"] == "dialogue" and b.get("speaker")]
    rows = sorted(lines, key=lambda r: int(r["ord"]))
    return {bid: str(r["id"]) for bid, r in zip(spoken, rows, strict=False)}
