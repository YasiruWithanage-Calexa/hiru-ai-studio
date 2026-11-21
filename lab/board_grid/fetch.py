"""Read-only: every finished Scene board (row + painted sheet) for the free sweep, and the pictures one part was painted
with, for the paid test.

    .venv/Scripts/python.exe lab/board_grid/fetch.py --all
    .venv/Scripts/python.exe lab/board_grid/fetch.py --target 34683023-2cd6-4bcd-ac9d-4ec6c9f4aa82 --name love_p2

Only GET requests. Writes `lab/board_grid/input/boards/<id>.json|png` and `input/<name>/`: board.json, ref_1.png ...
(the location plate, then the previous part's last panel when the part has one), refs.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]

from contracts.board import OVERLAP_LABEL  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402

FIELDS = "id,scene_id,production_id,version,part,parts,status,quality,prompt,cells,storage_path,created_at"


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


class Rest:
    def __init__(self) -> None:
        e = env()
        self.url, key = e["SUPABASE__URL"].rstrip("/"), e["SUPABASE__SERVICE_ROLE_KEY"]
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def get(self, path: str) -> bytes:
        req = urllib.request.Request(f"{self.url}{path}", headers=self.headers, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def rows(self, table: str, params: dict[str, str]) -> list[dict]:
        return json.loads(self.get(f"/rest/v1/{table}?{urllib.parse.urlencode(params)}"))

    def file(self, bucket: str, path: str) -> bytes:
        return self.get(f"/storage/v1/object/{bucket}/{urllib.parse.quote(path)}")


def fetch_all(rest: Rest) -> None:
    out = HERE / "input" / "boards"
    out.mkdir(parents=True, exist_ok=True)
    rows = rest.rows("scene_boards", {"status": "eq.done", "select": FIELDS, "order": "created_at.asc"})
    for b in rows:
        (out / f"{b['id']}.json").write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding="utf-8")
        png = out / f"{b['id']}.png"
        if not png.exists() and b.get("storage_path"):
            png.write_bytes(rest.file("frames", b["storage_path"]))
    print(f"{len(rows)} finished boards saved to {out}")


def fetch_target(rest: Rest, board_id: str, name: str) -> None:
    out = HERE / "input" / name
    out.mkdir(parents=True, exist_ok=True)
    b = rest.rows("scene_boards", {"id": f"eq.{board_id}", "select": FIELDS})[0]
    (out / "board.json").write_text(json.dumps(b, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "board_old.png").write_bytes(rest.file("frames", b["storage_path"]))
    refs = []
    scene = rest.rows("scenes", {"id": f"eq.{b['scene_id']}", "select": "location_id"})[0]
    if scene.get("location_id"):
        loc = rest.rows("canon_entities", {
            "id": f"eq.{scene['location_id']}",
            "select": "id,name,current:canon_versions!canon_entities_current_version_fkey(reference_assets)"})[0]
        if sheet_path(loc):
            refs.append({"label": f"the location plate for {loc['name']}", "bucket": "references",
                         "path": sheet_path(loc)})
    if int(b["part"]) > 1:
        prev = rest.rows("scene_boards", {"scene_id": f"eq.{b['scene_id']}", "version": f"eq.{b['version']}",
                                          "part": f"eq.{int(b['part']) - 1}", "select": "cells"})[0]
        last = [c for c in prev.get("cells") or [] if c.get("path")][-1]
        refs.append({"label": OVERLAP_LABEL, "bucket": "frames", "path": last["path"]})
    for i, r in enumerate(refs, 1):
        (out / f"ref_{i}.png").write_bytes(rest.file(r["bucket"], r["path"]))
    (out / "refs.json").write_text(json.dumps(refs, indent=1, ensure_ascii=False), encoding="utf-8")
    cited = [r["label"] for r in refs]
    print(f"saved to {out}: part {b['part']}/{b['parts']}, {len(b.get('cells') or [])} cells, refs {cited}")
    for r in refs:  # the saved prompt must cite exactly these, in this order, or the test is not the product's
        if r["label"] not in b["prompt"]:
            print(f"WARNING: the saved prompt does not cite {r['label']!r}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--target")
    ap.add_argument("--name")
    args = ap.parse_args()
    rest = Rest()
    if args.all:
        fetch_all(rest)
    if args.target:
        fetch_target(rest, args.target, args.name or args.target[:8])
    return 0


if __name__ == "__main__":
    sys.exit(main())
