"""The looks call's input, for a production WITH a breakdown (Ekama: its scenes, presence and timeline, plus the
refined cards of a canon refine run) and for one WITHOUT (You and I 7: today's scenes and canon cards; the model reads
story time itself). Both become the same shape. Pure, no model.

`truth` is what code knows for the checks: who is on screen in each scene (only the breakdown knows; None otherwise).
"""

from __future__ import annotations

import json
import re
from typing import Any

ON_SCREEN = {"on_screen", "body"}


def named(text: str, names: dict[str, str]) -> str:
    """The breakdown's prose writes ids ("C03 reveals evidence concerning C04"): give the model names instead."""
    return re.sub(r"\b[CLP]\d{2,3}\b", lambda m: names.get(m.group(0), m.group(0)), text)


def from_breakdown(export: dict[str, Any], refined: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    mem = export["memory"]
    names = {e["id"]: e["name"] for e in mem["entities"]}
    cards = {p["id"]: p for p in refined["people"]}
    people = [{"id": e["id"], "name": e["name"],
               "appearance": cards[e["id"]]["appearance"]["value"] if e["id"] in cards else "",
               "base_wardrobe": cards[e["id"]]["wardrobe"]["value"] if e["id"] in cards else ""}
              for e in mem["entities"] if e["kind"] == "person"]
    scenes, truth = [], {}
    for sc in mem["scenes"]:
        b = sc.get("brief") or {}
        script = []
        for blk in sc["blocks"]:
            if blk["kind"] == "dialogue" and blk.get("speaker"):
                how = "" if blk.get("presence", "on_screen") in ON_SCREEN else f" ({blk['presence'].replace('_', ' ')})"
                script.append(f"{names.get(blk['speaker'], blk['speaker'])}{how}: {blk['text']}")
            elif blk.get("text"):
                script.append(blk["text"])
        present = [{"person": f"{p['person']} {names.get(p['person'], '')}", "presence": p["presence"]}
                   for p in b.get("people", [])]
        scenes.append({"id": sc["id"], "heading": sc["heading"], "place": names.get(b.get("place", ""), ""),
                       "people": present, "script": script})
        truth[sc["id"]] = sorted(p["person"] for p in b.get("people", []) if p["presence"] in ON_SCREEN)
    timeline = [{k: t.get(k) for k in ("scene", "story_order", "story_day", "relative", "kind", "anchor")}
                for t in (mem.get("continuity") or {}).get("timeline", [])]
    every = {e["id"]: e["name"] for e in mem["entities"]}
    synopses = [{"episode": s["episode"], "text": named(s["text"], every)}
                for s in (mem.get("continuity") or {}).get("synopses", [])]
    return ({"episodes": synopses, "people": people, "scenes": scenes, "timeline": timeline},
            {"on_screen": truth, "people": {p["id"]: p["name"] for p in people}})


def from_tables(export: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    people = [{"id": p["code"], "name": p["name"], "appearance": p["card"].get("appearance", ""),
               "base_wardrobe": p["card"].get("wardrobe", ""), "notes": p["card"].get("notes", "")}
              for p in export["people"]]
    scenes = [{"id": s["key"], "heading": s["heading"], "title": s["title"], "place": s["place"] or "",
               "script": s["script"]} for s in export["scenes"]]
    episodes = [{"episode": e["number"], "title": e["title"], "text": e["synopsis"]} for e in export["episodes"]]
    return ({"episodes": episodes, "people": people, "scenes": scenes, "timeline": None},
            {"on_screen": None, "people": {p["id"]: p["name"] for p in people}})


def message(data: dict[str, Any]) -> str:
    return "THE PRODUCTION (JSON)\n" + json.dumps(data, ensure_ascii=False, indent=1)
