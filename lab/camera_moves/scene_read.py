"""Read-only: one scene of a production from the database (GET only, nothing written), for the camera_moves lab.

    .venv/Scripts/python.exe lab/camera_moves/scene_read.py --scene <scene id> --name love_s3

Writes runs/db_<name>/scene.json: the scene row (heading, script), its shots in number order (framing, duration, ir,
design, intent, lines), the shot's latest video prompt (prose) and whether it has an accepted first frame and a take.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "portrait_board"))
from fetch import Rest  # noqa: E402  the lab's read-only Supabase helper (GET only)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    rest = Rest()
    scene = rest.rows("scenes", {"id": f"eq.{args.scene}", "select": "*"})[0]
    shots = rest.rows("shots", {"scene_id": f"eq.{args.scene}", "select": "*", "order": "number.asc"})
    out_shots = []
    for s in shots:
        prompt = rest.rows("video_prompts", {"shot_id": f"eq.{s['id']}", "select": "id,version,prose",
                                             "order": "version.desc", "limit": "1"})
        frames = rest.rows("first_frames", {"shot_id": f"eq.{s['id']}", "status": "eq.done",
                                            "select": "id,status", "limit": "1"})
        takes = rest.rows("takes", {"shot_id": f"eq.{s['id']}", "select": "id,status", "limit": "3"})
        out_shots.append({**s, "prompt": prompt[0] if prompt else None, "has_frame": bool(frames),
                          "takes": takes})
    lines = rest.rows("dialogue_lines", {"scene_id": f"eq.{args.scene}", "select": "*", "order": "ord.asc"})
    canon = rest.rows("canon_entities", {"production_id": f"eq.{scene['production_id']}",
                                         "select": "id,code,name,kind,class"})
    production = rest.rows("productions", {"id": f"eq.{scene['production_id']}", "select": "*"})[0]
    out = HERE / "runs" / f"db_{args.name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "scene.json").write_text(json.dumps({"scene": scene, "shots": out_shots, "lines": lines, "canon": canon,
                                                "production": production}, indent=1, ensure_ascii=False,
                                               default=str), encoding="utf-8")
    print(f"{scene.get('heading')} | {len(shots)} shots")
    for s in out_shots:
        ir = s.get("ir") or {}
        cine = ir.get("cinematography") or {}
        print(f"  #{s['number']:>2} {s.get('framing', ''):7} {s.get('duration_s')}s frame={'Y' if s['has_frame'] else '-'}"
              f" takes={len(s['takes'])} | {str(cine.get('movement', ''))[:50]} | "
              f"{str((ir.get('subjects') or [{}])[0].get('action', ''))[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
