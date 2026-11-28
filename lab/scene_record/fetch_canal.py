"""READ-ONLY: the canal scene (Ekama Sakshiya E01-S01, the demo scene that went wrong) as this lab's input.

    .venv/Scripts/python.exe lab/scene_record/fetch_canal.py

GET requests only (the service-role REST client of scripts/_common.py). Writes input/canal.json: the script blocks with
their line words, the people with their card appearance, the look in force and the scene condition, the place with its
six named views, and the props the scene names. Nothing in the database or src/ changes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _common import Rest, load_env  # noqa: E402

SCENE = "8b09b5ab-dac4-4e79-a71b-53ad4e369970"
PROPS = ("small medical bag", "small metal key", "phone")


def main() -> int:
    load_env()
    r = Rest()
    scene = r.get("scenes", id=f"eq.{SCENE}", select="id,production_id,heading,time_of_day,envelope_s,script,location_id")[0]
    pid = scene["production_id"]
    lines = {str(ln["ord"]): ln for ln in r.get("dialogue_lines", scene_id=f"eq.{SCENE}", select="ord,speaker,text")}
    ents = r.get("canon_entities", production_id=f"eq.{pid}", select="id,kind,code,name,class,current_version_id")

    def card(e: dict) -> dict:
        return r.get("canon_versions", id=f"eq.{e['current_version_id']}", select="card,reference_assets")[0]

    picks = {p["entity_id"]: p for p in r.get("scene_looks", scene_id=f"eq.{SCENE}", select="entity_id,look_id,condition")}
    people = []
    for e in ents:
        if e["kind"] != "character" or e["id"] not in picks:
            continue
        look = r.get("canon_looks", id=f"eq.{picks[e['id']]['look_id']}", select="name,outfit,hair,accessories")[0]
        people.append({"id": e["code"], "name": e["name"], "appearance": card(e)["card"].get("appearance", ""),
                       "look": look, "condition": picks[e["id"]]["condition"]})
    loc = next(e for e in ents if e["id"] == scene["location_id"])
    lv = card(loc)
    views = next((a["views"] for a in lv.get("reference_assets") or [] if a.get("views")), [])
    props = [{"id": e["code"], "name": e["name"], "details": card(e)["card"].get("details", "")}
             for e in ents if e["kind"] == "prop" and e["name"] in PROPS]
    blocks, n_line = [], 0
    for i, b in enumerate(scene["script"]):
        row = {"n": i, "kind": b["kind"], "text": b["text"]}
        if b["kind"] == "dialogue":
            ln = lines.get(str(n_line)) or {}
            row.update(line_id=f"L{n_line + 1}", speaker=ln.get("speaker", ""), words=ln.get("text", ""))
            n_line += 1
        blocks.append(row)
    out = {
        "id": "canal",
        "title": "Ekama Sakshiya E01-S01, The canal discovery",
        "heading": scene["heading"],
        "time_of_day": scene["time_of_day"],
        "length_s": scene["envelope_s"],
        "blocks": blocks,
        "people": people,
        "place": {"id": loc["code"], "name": loc["name"], "look": lv["card"].get("look", ""),
                  "views": [{"n": v["n"], "name": v["name"], "camera": v.get("camera", ""),
                             "sees": v.get("sees") or v.get("what", "")} for v in views]},
        "props": props,
    }
    (HERE / "input" / "canal.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote input/canal.json:", len(blocks), "blocks,", len(people), "people,", len(props), "props")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
