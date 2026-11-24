"""Read the fixed-marks lab's case out of the hosted dev database into `input/` (read-only: GET requests only).

The case: Love Hour scene 4 (de75bc31, "A conversation that changes everything"), the CURRENT Scene board's part 1
(the one the person showed on 2026-11-24: shots 1-6, Kasun red, Anudi blue, the stall drifting from behind Kasun to
behind the wall). Saved: the part's row (writer, prompt, cells), its picture, the very pictures its prompt names (the
location's views sheet, the vehicle sheets or plates), and the scene's staging map (`scenes.staging`).

    .venv/Scripts/python.exe lab/fixed_marks/fetch.py
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
from contracts.canon import views_asset  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402

PROD = "b89f79a3-3ce6-4123-aee5-759f35c09d69"
SCENE = "de75bc31-d118-4943-b384-1a231698f55a"


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
    """No arguments: scene 4's part 1 into `input/` (runs A, B, C, T). `<case> <scene id> <part>` (phase 0 of
    plan/2026-11-24d): that scene's newest finished board, that part, into `input_<case>/`."""
    case, scene_id, part = (sys.argv[1], sys.argv[2], int(sys.argv[3])) if len(sys.argv) == 4 else ("", SCENE, 1)
    out = HERE / (f"input_{case}" if case else "input")
    out.mkdir(exist_ok=True)
    canon = rows("canon_entities", production_id=f"eq.{PROD}",
                 select="id,name,kind,current:canon_versions!canon_entities_current_version_fkey(*)")
    scene = rows("scenes", id=f"eq.{scene_id}", select="id,number,title,staging,script")[0]
    (out / "script.json").write_text(json.dumps(scene.get("script") or [], ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    (out / "staging.json").write_text(json.dumps(scene.get("staging") or {}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")

    # the newest FINISHED part 1 (a newer version may be painting while the lab reads)
    boards = rows("scene_boards", scene_id=f"eq.{scene_id}", status="eq.done", part=f"eq.{part}", select="*",
                  order="version.desc", limit="1")
    if not boards:
        raise SystemExit(f"no finished part {part} of the scene's board")
    part1 = boards[0]
    shots = rows("shots", scene_id=f"eq.{scene_id}", select="id,number,block_start,block_end", order="number.asc")
    (out / "shots.json").write_text(json.dumps(shots, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "board_part1.json").write_text(json.dumps(part1, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "board_part1.png").write_bytes(file("frames", part1["storage_path"]))
    (out / "board_part1_prompt.txt").write_text(part1.get("prompt") or "", encoding="utf-8")

    # the pictures its prompt names, in order, found by the name each label ends with
    head = (part1.get("prompt") or "").split("Reference images, in order:", 1)
    labels = re.findall(r"[Ii]mage \d+ is (.+?)(?=, numbered|\. Take|; image|\.\s)", head[1]) if len(head) == 2 else []
    refs = []
    for i, label in enumerate(labels, 1):
        if label.startswith(kit.OVERLAP_LABEL):  # the previous part's last panel
            prev = rows("scene_boards", scene_id=f"eq.{scene_id}", version=f"eq.{part1['version']}",
                        part=f"eq.{part1['part'] - 1}", select="cells")[0]
            last = max((c for c in prev["cells"] if c.get("panel") and c.get("path")), key=lambda c: c["panel"])
            (out / f"ref_{i}.png").write_bytes(file("frames", last["path"]))
            refs.append({"label": kit.OVERLAP_LABEL, "file": f"ref_{i}.png", "name": "", "views": [], "layout": "",
                         "empty": []})
            continue
        row = next((c for c in canon if label.rstrip(":").split(":")[0].split(" for ", 1)[-1].startswith(c["name"])),
                   None)
        if row is None:
            raise SystemExit(f"no canon row for picture label: {label}")
        asset = views_asset(row)
        path = str(asset["path"]) if asset is not None and "sheet" in label else sheet_path(row)
        (out / f"ref_{i}.png").write_bytes(file("references", path))
        refs.append({"label": label, "file": f"ref_{i}.png", "name": row["name"],
                     "views": list((asset or {}).get("views") or []), "layout": (asset or {}).get("layout", ""),
                     "empty": (asset or {}).get("empty", [])})
    (out / "refs.json").write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"scene {scene['number']} {scene['title']!r}; board v{part1['version']} part {part1['part']} of {part1['parts']} "
          f"({len([c for c in part1['cells'] if c.get('panel')])} panels, approved {bool(part1.get('approved_at'))}); "
          f"pictures: {[r['label'] for r in refs]}; staging marks: "
          f"{len((scene.get('staging') or {}).get('marks') or [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
