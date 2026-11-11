"""What each model call is sent (plan/2026-11-11 §4.3, §4.4): built by code from the breakdown memory, so every call
sees the same
ids and the same words."""

from __future__ import annotations

import json
from typing import Any

from contracts.breakdown.lines import Doc
from contracts.breakdown.schema import Breakdown


def roster(bd: Breakdown) -> str:
    rows = []
    for e in bd.entities:
        extra = f", {e.place_kind}" + (f" in {e.within}" if e.within else "") if e.kind == "place" else ""
        facts = "; ".join(f"{k}: {v.value}" for k, v in e.card.items() if k != "summary")
        rows.append(f"{e.id} [{e.kind}{extra}] {e.name}" + (f" - {facts}" if facts else ""))
    return "\n".join(rows)


def rules(bd: Breakdown) -> str:
    out = []
    for r in bd.rules:
        scope = "all scenes" if r.scope_kind == "all" else f"{r.scope_kind} {r.scope_id}"
        out.append(f"{r.id} [{r.about}, {scope}] {' '.join(r.text.split())}")
    return "\n".join(out)


def story(bd: Breakdown, doc: Doc) -> str:
    """Every scene's lines, numbered with the document's own line numbers, under its scene id."""
    parts = []
    for sc in bd.scenes:
        body = "\n".join(f"{n}: {doc.lines[n - 1]}" for n in range(sc.heading_line, sc.last + 1))
        parts.append(f"=== {sc.id} ===\n{body}")
    return "\n\n".join(parts)


def continuity_user(bd: Breakdown, doc: Doc) -> str:
    return f"CAST, PLACES, THINGS\n{roster(bd)}\n\nDIRECTION RULES\n{rules(bd)}\n\nSTORY\n{story(bd, doc)}"


def _brief_continuity(cont: dict[str, Any], scenes: list[str]) -> str:
    """The continuity facts as compact JSON: whole-story facts, with timeline and knowledge kept for the scenes asked
    for."""
    keep = {k: v for k, v in cont.items() if k not in ("timeline", "knowledge", "scopes")}
    keep["timeline"] = cont["timeline"]
    keep["knowledge"] = [k for k in cont["knowledge"] if k["scene"] in scenes]
    keep["scopes"] = [s for s in cont["scopes"] if set(s["scenes"]) & set(scenes)]

    def strip(x: Any) -> Any:  # lines and reasons are for people; the model needs the facts
        if isinstance(x, dict):
            return {
                k: strip(v)
                for k, v in x.items()
                if k not in ("lines", "reason", "source") or (k == "source" and v == "inferred")
            }
        return [strip(i) for i in x] if isinstance(x, list) else x

    return json.dumps(strip(keep), ensure_ascii=False)


def episode_user(bd: Breakdown, doc: Doc, cont: dict[str, Any], scenes: list[str], before: str = "") -> str:
    chosen = [s for s in bd.scenes if s.id in scenes]
    body = "\n\n".join(
        f"=== {s.id} (place card: pick from the cards) ===\n"
        + "\n".join(f"{n}: {doc.lines[n - 1]}" for n in range(s.heading_line, s.last + 1))
        for s in chosen
    )
    return (
        f"CARDS\n{roster(bd)}\n\nDIRECTION RULES\n{rules(bd)}\n\nCONTINUITY\n{_brief_continuity(cont, scenes)}\n\n"
        f"END OF THE EPISODE BEFORE\n{before or 'none: this is the first episode'}\n\nSCENES TO BREAK DOWN\n{body}"
    )
