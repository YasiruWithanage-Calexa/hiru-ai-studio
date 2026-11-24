"""Read the place views lab's four places out of the hosted dev database into `input/` (read-only: GET requests only):
each place's canon row and plate (when it has one) and the scripts of the scenes set there.

    .venv/Scripts/python.exe lab/place_views/fetch.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts.frame_brief import sheet_path  # noqa: E402

PROD = "b89f79a3-3ce6-4123-aee5-759f35c09d69"  # Love Hour
# lab key -> canon code: one place of each type
PLACES = {"roadside": "L02", "restaurant": "L10", "prep_room": "L08", "car": "L04"}


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


E = env()
URL = E["SUPABASE__URL"].rstrip("/")
H = {"apikey": E["SUPABASE__SERVICE_ROLE_KEY"], "Authorization": f"Bearer {E['SUPABASE__SERVICE_ROLE_KEY']}"}


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
                 select="*,current:canon_versions!canon_entities_current_version_fkey(*)")
    scenes = rows("scenes", production_id=f"eq.{PROD}", select="id,number,heading,title,location_id,script",
                  order="number.asc")
    by_code = {c.get("code"): c for c in canon}
    places = {}
    for key, code in PLACES.items():
        row = by_code[code]
        card = (row.get("current") or {}).get("card") or {}
        spots = [{"name": c["name"], "look": ((c.get("current") or {}).get("card") or {}).get("look", "")}
                 for c in canon if str(c.get("parent_id") or "") == row["id"]]
        mine = [s for s in scenes if s.get("location_id") == row["id"]]
        # a vehicle has no scene of its own: the scenes whose words name it ("car")
        if row.get("class") == "vehicle":
            mine = [s for s in scenes if "car" in json.dumps(s.get("script") or "", ensure_ascii=False).lower()]
        plate = ""
        if sheet_path(row):
            plate = f"{key}_plate.png"
            (out / plate).write_bytes(file("references", sheet_path(row)))
        places[key] = {"code": code, "name": row["name"], "class": row.get("class"), "look": card.get("look", ""),
                       "spots": spots, "plate": plate,
                       "scenes": [{"number": s["number"], "heading": s.get("heading"), "script": s.get("script")}
                                  for s in mine]}
        print(f"{key}: {row['name']} ({row.get('class')}), plate {'yes' if plate else 'no'}, {len(spots)} spots, "
              f"{len(mine)} scenes")
    (out / "places.json").write_text(json.dumps(places, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
