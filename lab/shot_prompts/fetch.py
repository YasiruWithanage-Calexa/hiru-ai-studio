"""Read-only (GET only, nothing written to the database): one shot's inputs for the shot_prompts lab.

    .venv/Scripts/python.exe lab/shot_prompts/fetch.py --slates 2A-1,2B-1,2H-1

From the person's scene read by lab/camera_moves (runs/db_url_scene/scene.json). Per shot, runs/<slate>/inputs/:
today_frame.png + today_frame_prompt.txt (the accepted first frame and the prompt it was painted from: for comparison
only, never sent), face_<code>.png / look_<code>.png (the people in frame, the look the frame was pinned to), place_<n>.png
(the location plates the frame used), meta.json (people with their card appearance and look fields, places, style).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "lab" / "portrait_board"))
from fetch import Rest  # noqa: E402  GET only

SCENE = ROOT / "lab" / "camera_moves" / "runs" / "db_url_scene" / "scene.json"


def _asset(assets: list[dict], *kinds: str) -> str | None:
    for kind in kinds:
        hit = next((a["path"] for a in assets or [] if a.get("kind") == kind and a.get("path")), None)
        if hit:
            return hit
    return next((a["path"] for a in assets or [] if a.get("path")), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slates", required=True)
    args = ap.parse_args()
    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    shots = {s["slate"]: s for s in scene["shots"]}
    rest = Rest()
    for slate in [s.strip() for s in args.slates.split(",") if s.strip()]:
        shot = shots[slate]
        out = HERE / "runs" / slate / "inputs"
        out.mkdir(parents=True, exist_ok=True)
        frames = rest.rows("first_frames", {"shot_id": f"eq.{shot['id']}", "status": "eq.done", "select": "*",
                                            "order": "accepted_at.desc.nullslast,created_at.desc"})
        frame = next((f for f in frames if f.get("accepted_at")), frames[0])
        (out / "today_frame.png").write_bytes(rest.file("frames", frame["storage_path"]))
        (out / "today_frame_prompt.txt").write_text(frame.get("prompt") or "", encoding="utf-8")
        ids = list(dict.fromkeys(frame.get("reference_ids") or []))
        rows = rest.rows("canon_entities", {
            "id": f"in.({','.join(ids)})",
            "select": "id,code,name,kind,current:canon_versions!canon_entities_current_version_fkey(version,card,"
                      "reference_assets,wardrobe_anchor)"}) if ids else []
        pinned = ((frame.get("pins") or {}).get("looks")) or {}
        people, places = [], []
        codes = [s.get("id") for s in (shot.get("ir") or {}).get("subjects") or []]
        for r in rows:
            cur = r.get("current") or {}
            assets = cur.get("reference_assets") or []
            if r["kind"] == "character":
                face = _asset(assets, "face", "sheet")
                look_id = (pinned.get(r["id"]) or {}).get("id")
                look = rest.rows("canon_looks", {"id": f"eq.{look_id}", "select": "*"})[0] if look_id else None
                look_path = _asset(look["sheet_assets"], "look") if look else _asset(assets, "sheet")
                (out / f"face_{r['code']}.png").write_bytes(rest.file("references", face))
                (out / f"look_{r['code']}.png").write_bytes(rest.file("references", look_path))
                card = cur.get("card") or {}
                people.append({"code": r["code"], "name": r["name"], "in_frame": r["code"] in codes,
                               "appearance": card.get("appearance") or card.get("summary") or "",
                               "look": {k: (look or {}).get(k, "") for k in ("name", "outfit", "hair", "makeup",
                                                                              "accessories")}})
            else:
                path = _asset(assets, "plate", "sheet")
                if path:
                    n = len(places) + 1
                    (out / f"place_{n}.png").write_bytes(rest.file("references", path))
                    places.append({"n": n, "name": r["name"], "code": r["code"]})
        style = (frame.get("prompt") or "").split(". Reference images")[0].strip()
        meta = {"slate": slate, "shot_id": shot["id"], "duration_s": shot["duration_s"], "people": people,
                "places": places, "style": style, "aspect_ratio": "9:16"}
        (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{slate}: people {[(p['code'], p['name'][:30], p['in_frame']) for p in people]}; "
              f"places {[p['name'] for p in places]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
