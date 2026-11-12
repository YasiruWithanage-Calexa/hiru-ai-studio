"""The refine call's input, built by code from the export (no model). Pure.

The model sees: the documents' numbered lines once (Ekama is 61 lines; the product would send each entity's scenes
instead), the breakdown's entities with what it already knows (kind, place kind, seen, within, the lines of its card,
the scenes it is in), the scenes' briefs, the palette and lighting rules, the continuity looks and timeline, and every
canon entry a PERSON wrote (their words win and are context, never rewritten).
"""

from __future__ import annotations

import json
from typing import Any

from contracts.canon import name_key

RULE_ABOUT = ("palette", "lighting")


def numbered(sources: list[dict[str, Any]]) -> list[str]:
    """Every document's lines, numbered as the breakdown numbers them (one text, documents one after another)."""
    out, n = [], 0
    for s in sources:
        for line in s["body"]["lines"]:
            n += 1
            out.append(f"{n:>4}| {line}")
    return out


def scenes_of(memory: dict[str, Any]) -> dict[str, list[str]]:
    """entity id -> the scene ids the breakdown puts it in (place, people, things, event spots and actors)."""
    found: dict[str, list[str]] = {}

    def add(eid: str, sid: str) -> None:
        if eid and sid not in found.setdefault(eid, []):
            found[eid].append(sid)

    for sc in memory["scenes"]:
        b = sc.get("brief") or {}
        add(b.get("place", ""), sc["id"])
        for p in b.get("people", []):
            add(p["person"], sc["id"])
        for t in b.get("things", []):
            add(t["thing"], sc["id"])
        for blk in sc.get("blocks", []):
            if blk.get("speaker"):
                add(blk["speaker"], sc["id"])
            for ev in blk.get("events", []):
                add(ev.get("spot", ""), sc["id"])
                for a in ev.get("actors", []):
                    add(a, sc["id"])
                for t in ev.get("things", []):
                    add(t, sc["id"])
    return found


def person_canon(canon: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """(kind, name key) -> a canon entry whose current card a person wrote, with its non-empty fields."""
    kinds = {"character": "person", "location": "place", "prop": "thing"}
    out = {}
    for c in canon:
        if c.get("source") == "user":  # locked alone is not a person's words (Ekama's locked cast is still extract)
            card = {k: v for k, v in (c.get("card") or {}).items() if v}
            out[(kinds[c["kind"]], name_key(c["name"]))] = {"code": c["code"], "card": card, "locked": c["locked"]}
    return out


def build(export: dict[str, Any]) -> dict[str, Any]:
    mem = export["memory"]
    names = {e["id"]: e["name"] for e in mem["entities"]}
    in_scenes = scenes_of(mem)
    by_person = person_canon(export["canon"])
    entities = []
    for e in mem["entities"]:
        item: dict[str, Any] = {
            "id": e["id"], "kind": e["kind"], "name": e["name"], "card_lines": e["lines"],
            "seen": e.get("seen", True), "scenes": in_scenes.get(e["id"], []),
        }
        if e["kind"] == "place":
            item["place_kind"] = e.get("place_kind")
            item["within"] = f"{e['within']} {names.get(e['within'], '')}".strip() if e.get("within") else ""
        if e["card"].get("summary", {}).get("source") == "inferred":
            item["implied"] = e["card"]["summary"]["value"]
        pc = by_person.get((e["kind"], name_key(e["name"])))
        if pc:
            item["a_person_wrote"] = pc["card"]
        entities.append(item)
    scenes = []
    for sc in mem["scenes"]:
        b = sc.get("brief") or {}
        scenes.append({
            "id": sc["id"], "heading": sc["heading"], "lines": [sc["heading_line"], sc["last"]],
            "place": b.get("place", ""), "mood": b.get("mood", []),
            "people": [p["person"] for p in b.get("people", [])],
            "things": [f"{t['thing']} ({t['role']})" for t in b.get("things", [])],
        })
    places = {e["id"] for e in mem["entities"] if e["kind"] == "place"}
    rules = [{"id": r["id"], "about": r["about"], "text": r["text"],
              "applies_to": names.get(r["scope_id"], r["scope_id"]) if r["scope_id"] in places else r["scope_kind"]}
             for r in mem["rules"] if r["about"] in RULE_ABOUT]
    cont = mem.get("continuity") or {}
    return {
        "document": numbered(export["sources"]),
        "entities": entities,
        "scenes": scenes,
        "direction_rules": rules,
        "continuity": {
            "looks": cont.get("looks", []),
            "timeline": [{k: t.get(k) for k in ("scene", "story_order", "kind", "relative")} for t in cont.get("timeline", [])],
        },
    }


def message(export: dict[str, Any]) -> str:
    data = build(export)
    doc = "\n".join(data.pop("document"))
    return (f"THE DOCUMENTS (numbered lines)\n{doc}\n\nTHE BREAKDOWN (JSON)\n"
            f"{json.dumps(data, ensure_ascii=False, indent=1)}")
