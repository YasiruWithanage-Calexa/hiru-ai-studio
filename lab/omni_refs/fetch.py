"""Read-only: one shot's video prompt, its accepted first frame, and the face + look sheets of the people it shows.

    .venv/Scripts/python.exe lab/omni_refs/fetch.py --shot <shot id> --name shot02

Only GET requests. Writes `lab/omni_refs/input/<name>/`: shot.json (prose, frame, people, aspect), frame.png and, per
person on screen, face_<code>.png and look_<code>.png (the look the first frame was pinned to, else the base sheet).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "portrait_board"))
from fetch import Rest  # noqa: E402  the lab's read-only Supabase helper


def _asset(assets: list[dict], kind: str) -> str | None:
    return next((a["path"] for a in assets or [] if a.get("kind") == kind and a.get("path")), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    out = HERE / "input" / args.name
    out.mkdir(parents=True, exist_ok=True)
    rest = Rest()

    shot = rest.rows("shots", {"id": f"eq.{args.shot}", "select": "id,number,production_id,ir,duration_s"})[0]
    prod = rest.rows("productions", {"id": f"eq.{shot['production_id']}", "select": "*"})[0]
    prompt = rest.rows("video_prompts", {"shot_id": f"eq.{args.shot}", "select": "id,version,prose",
                                         "order": "version.desc", "limit": "1"})[0]
    frames = rest.rows("first_frames", {"shot_id": f"eq.{args.shot}", "status": "eq.done", "select": "*",
                                        "order": "accepted_at.desc.nullslast,created_at.desc"})
    frame = next((f for f in frames if f.get("accepted_at")), frames[0])
    (out / "frame.png").write_bytes(rest.file("frames", frame["storage_path"]))

    # The people on screen, in the shot's order (`ir.subjects`), by canon code.
    codes = [s["id"] for s in (shot.get("ir") or {}).get("subjects") or [] if s.get("id")]
    canon = rest.rows("canon_entities", {
        "production_id": f"eq.{shot['production_id']}", "code": f"in.({','.join(codes)})",
        "select": "id,name,code,kind,current:canon_versions!canon_entities_current_version_fkey(version,reference_assets)"})
    pinned_looks = ((frame.get("pins") or {}).get("looks")) or {}
    people = []
    for code in codes:
        row = next((r for r in canon if r["code"] == code), None)
        if row is None or row["kind"] != "character":
            continue
        assets = (row.get("current") or {}).get("reference_assets") or []
        face = _asset(assets, "face") or _asset(assets, "sheet")
        (out / f"face_{code}.png").write_bytes(rest.file("references", face))
        look_id = (pinned_looks.get(row["id"]) or {}).get("id")
        look = rest.rows("canon_looks", {"id": f"eq.{look_id}", "select": "*"})[0] if look_id else None
        look_path = _asset(look["sheet_assets"], "look") if look else _asset(assets, "sheet")
        (out / f"look_{code}.png").write_bytes(rest.file("references", look_path))
        people.append({"code": code, "name": row["name"], "look_name": look["name"] if look else "base sheet",
                       "outfit": look.get("outfit") if look else None,
                       "accessories": look.get("accessories") if look else None})

    video = ((prod.get("settings") or {}).get("video") or {})
    meta = {"shot_id": args.shot, "shot_number": shot["number"], "duration_s": shot["duration_s"],
            "aspect_ratio": video.get("aspect_ratio") or prod.get("aspect_ratio") or "9:16",
            "prompt_id": prompt["id"], "prompt_version": prompt["version"], "prose": prompt["prose"],
            "frame_id": frame["id"], "people": people}
    (out / "shot.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved to {out}: shot {shot['number']}, frame {frame['id'][:8]}, "
          f"people {[(p['code'], p['name'], p['look_name']) for p in people]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
