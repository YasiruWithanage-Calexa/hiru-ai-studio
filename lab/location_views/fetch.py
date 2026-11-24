"""Read the lab's case out of the hosted dev database into `input/` (read-only: GET requests only).

The case: Love Hour scene 4 (de75bc31, "A conversation that changes everything"), its location "Colombo roadside" and
the "Food three-wheeler" place, the current Scene board's part 1 (6 panels: its saved prompt and writer, its picture)
and shot 1's latest first frame (its prompt and the pictures it was painted with).

    .venv/Scripts/python.exe lab/location_views/fetch.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts import board as kit  # noqa: E402
from contracts.canon import face_sheet_path, look_sheet_path  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402

PROD = "b89f79a3-3ce6-4123-aee5-759f35c09d69"
SCENE = "de75bc31-d118-4943-b384-1a231698f55a"
PLACES = ("Colombo roadside", "Food three-wheeler")


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


E = env()
URL = E["SUPABASE__URL"].rstrip("/")
KEY = E["SUPABASE__SERVICE_ROLE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def rows(table: str, **params: str) -> list[dict]:
    r = httpx.get(f"{URL}/rest/v1/{table}", params=params, headers=H, timeout=60)
    r.raise_for_status()
    return r.json()


def file(bucket: str, path: str) -> bytes:
    r = httpx.get(f"{URL}/storage/v1/object/{bucket}/{path}", headers=H, timeout=120)
    r.raise_for_status()
    return r.content


def main() -> int:
    out = HERE / "input"
    out.mkdir(exist_ok=True)
    canon = rows("canon_entities", production_id=f"eq.{PROD}",
                 select="id,name,kind,current:canon_versions!canon_entities_current_version_fkey(*)")
    places = []
    for name in PLACES:
        row = next(c for c in canon if c["name"] == name)
        path = sheet_path(row)
        (out / f"place_{len(places) + 1}.png").write_bytes(file("references", path))
        card = (row.get("current") or {}).get("card") or {}
        places.append({"name": name, "look": card.get("look", ""), "file": f"place_{len(places) + 1}.png"})
    (out / "places.json").write_text(json.dumps(places, ensure_ascii=False, indent=1), encoding="utf-8")

    boards = rows("scene_boards", scene_id=f"eq.{SCENE}", select="*")
    part1 = kit.current_parts(boards)[0]
    (out / "board_part1.json").write_text(json.dumps(part1, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "board_part1.png").write_bytes(file("frames", part1["storage_path"]))

    shot = rows("shots", scene_id=f"eq.{SCENE}", number="eq.1", select="id,design")[0]
    frames = rows("first_frames", shot_id=f"eq.{shot['id']}", status="eq.done", select="*", order="created_at.desc",
                  limit="1")
    if frames:
        f = frames[0]
        (out / "frame_shot1.json").write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "frame_shot1.png").write_bytes(file("frames", f["storage_path"]))
        # the very pictures it was painted with, in its prompt's order, by their labels
        labels = re.findall(r"image \d+ is (.+?)(?:;|\. )", f["prompt"].split("Match them")[0])
        by_name = {c["name"]: c for c in canon}
        picks = rows("scene_looks", scene_id=f"eq.{SCENE}", select="entity_id,look_id")
        looks = {p["entity_id"]: rows("canon_looks", id=f"eq.{p['look_id']}", select="*")[0] for p in picks}
        cell = next(c for c in part1["cells"] if c["shot_id"] == shot["id"])
        refs = []
        for i, label in enumerate(labels, 1):
            name = re.sub(r" \(.*\)$", "", label.split(" for ", 1)[-1])
            if label.startswith("the face sheet for "):
                bucket, path = "references", face_sheet_path(by_name[name])
            elif label.startswith("the look sheet for "):
                bucket, path = "references", look_sheet_path(looks[by_name[name]["id"]])
            elif label.startswith(("the location plate for ", "the reference sheet for ")):
                bucket, path = "references", sheet_path(by_name[name])
            elif label.startswith("the approved scene board panel"):
                bucket, path = "frames", cell["path"]
            else:
                raise SystemExit(f"unknown picture label: {label}")
            (out / f"frame_ref_{i}.png").write_bytes(file(bucket, path))
            refs.append({"label": label, "file": f"frame_ref_{i}.png"})
        (out / "frame_refs.json").write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"places: {[p['name'] for p in places]}; board v{part1['version']} part 1 "
          f"({len([c for c in part1['cells'] if c.get('panel')])} panels, approved {bool(part1.get('approved_at'))}); "
          f"shot 1 frame: {frames[0]['created_at'] + ' board ' + str(frames[0].get('board_id')) if frames else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
