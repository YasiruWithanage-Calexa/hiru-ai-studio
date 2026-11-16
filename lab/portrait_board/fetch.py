"""Read-only: the saved Scene board, one first frame painted from it, and the pictures they were painted with.

    .venv/Scripts/python.exe lab/portrait_board/fetch.py --board <board id> --frame <frame id> --name scene1

Only GET requests. Writes `lab/portrait_board/input/<name>/`: board.json, frame.json, board_old.png,
cell_old_NNN.png (the board's own crops), and ref_<canon id>.png for every canon sheet the frame cites.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--frame", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    out = HERE / "input" / args.name
    out.mkdir(parents=True, exist_ok=True)
    rest = Rest()

    board = rest.rows("scene_boards", {"id": f"eq.{args.board}", "select": "*"})[0]
    frame = rest.rows("first_frames", {"id": f"eq.{args.frame}", "select": "*"})[0]
    (out / "board.json").write_text(json.dumps(board, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "frame.json").write_text(json.dumps(frame, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "board_old.png").write_bytes(rest.file("frames", board["storage_path"]))
    for c in board.get("cells") or []:
        if c.get("path"):
            (out / f"cell_old_{int(c['number']):03d}.png").write_bytes(rest.file("frames", c["path"]))

    ids = [str(i) for i in frame.get("reference_ids") or []]
    canon = rest.rows("canon_entities", {
        "id": f"in.({','.join(ids)})",
        "select": "id,name,code,current:canon_versions!canon_entities_current_version_fkey(reference_assets)"})
    refs = []
    for cid in ids:  # the frame's own order
        row = next(r for r in canon if r["id"] == cid)
        sheet = next(a for a in row["current"]["reference_assets"] if a.get("kind") == "sheet")
        (out / f"ref_{cid}.png").write_bytes(rest.file("references", sheet["path"]))
        refs.append({"id": cid, "name": row["name"], "code": row["code"]})
    (out / "refs.json").write_text(json.dumps(refs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved to {out}: board v{board['version']} ({len(board.get('cells') or [])} cells), "
          f"frame {frame['id'][:8]}, refs {[r['code'] for r in refs]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
