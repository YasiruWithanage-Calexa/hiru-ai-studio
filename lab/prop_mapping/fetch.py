"""Prop mapping lab (2026-11-25): read the case into `input/` (read-only: GET requests only; no model call).

The case: Love Hour scene 4 (de75bc31), shot 1 (and shot 11), from the CURRENT Scene board (v22). Saved: the product's
newest first frame of the shot (its prompt, picture and checks: the baseline), the shot's board panel, the writer's
panel words, and every picture the frame prompt names, plus the umbrella, handbag and bag sheets the product did not
attach.

    .venv/Scripts/python.exe lab/prop_mapping/fetch.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "fixed_marks"), str(ROOT / "src" / "libs")]

import fetch  # noqa: E402  (read-only helper: the hosted dev database, GET only)

from contracts import board as kit  # noqa: E402
from contracts.canon import face_sheet_path, look_sheet_path, views_asset  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

SHOTS = {1: "f121e389-49f5-46ae-8911-39db44462e49", 11: "7dec3cf5-b579-4850-b574-f8801be628c0"}
PROPS = ("phone", "umbrella", "handbag", "bag", "flask")


def main() -> int:
    out = HERE / "input"
    out.mkdir(exist_ok=True)
    canon = fetch.rows("canon_entities", production_id=f"eq.{fetch.PROD}",
                       select="id,name,kind,code,current:canon_versions!canon_entities_current_version_fkey(*)")
    by_id = {str(c["id"]): c for c in canon}
    by_name = {str(c["name"]).lower(): c for c in canon}
    picks = {p["entity_id"]: p["look_id"] for p in fetch.rows("scene_looks", scene_id=f"eq.{fetch.SCENE}",
                                                                select="entity_id,look_id")}
    files: dict[str, str] = {}

    def save(name: str, bucket: str, path: str) -> None:
        if path and name not in files:
            (out / name).write_bytes(fetch.file(bucket, path))
            files[name] = path

    for who in ("kasun", "anudi"):
        row = by_name[who]
        save(f"{who}_face.png", "references", face_sheet_path(row))
        look_id = picks.get(row["id"])
        if look_id:
            look = fetch.rows("canon_looks", id=f"eq.{look_id}", select="*")[0]
            save(f"{who}_look.png", "references", look_sheet_path(look))
    for p in PROPS:
        row = by_name.get(p)
        if row is not None:
            save(f"prop_{p}.png", "references", sheet_path(row))
    scene = fetch.rows("scenes", id=f"eq.{fetch.SCENE}", select="location_id")[0]
    loc = by_id[str(scene["location_id"])]
    asset = views_asset(loc)
    views = [dict(v) for v in (asset or {}).get("views") or []]
    sheet = fetch.file("references", str(asset["path"])) if asset else b""
    vehicle = by_name["food three-wheeler"]
    save("vehicle_plate.png", "references", sheet_path(vehicle))

    cases = {}
    for n, sid in SHOTS.items():
        f = fetch.rows("first_frames", shot_id=f"eq.{sid}", status="eq.done", select="*", order="created_at.desc",
                       limit="1")[0]
        (out / f"frame_shot{n}.json").write_text(json.dumps(f, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / f"frame_shot{n}.png").write_bytes(fetch.file("frames", f["storage_path"]))
        board = fetch.rows("scene_boards", id=f"eq.{f['board_id']}", select="*")[0]
        cell = next(c for c in board["cells"] if str(c.get("shot_id")) == sid and c.get("path") or
                    str(c.get("shot_id")) == sid and c.get("box"))
        if cell.get("path"):
            data = fetch.file("frames", cell["path"])
        else:
            data = pics.crop(fetch.file("frames", board["storage_path"]), cell["box"])
        (out / f"panel_shot{n}.png").write_bytes(data)
        writer = kit.Writer.of(board["writer"])
        panel = writer.panel(int(cell["number"]))
        view = next((v for v in views if panel and int(v.get("n") or 0) == panel.view), None)
        if view and view.get("box") and sheet:  # as `frame_render.graph._view_picture`
            (out / f"view_shot{n}.png").write_bytes(pics.crop(sheet, [int(x) for x in view["box"]]))
        cases[n] = {"shot_id": sid, "board_id": f["board_id"], "board_version": board["version"],
                    "cell": {k: cell.get(k) for k in ("number", "box", "path", "source")},
                    "panel": json.loads(json.dumps(panel, default=lambda o: o.__dict__)) if panel else None,
                    "colours": {by_id[k]["name"] if k in by_id else k: v for k, v in (board["colours"] or {}).items()},
                    "view": panel.view if panel else 0, "checks": f.get("checks")}
    (out / "sheet_views.png").write_bytes(sheet)
    (out / "views.json").write_text(json.dumps(views, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "files.json").write_text(json.dumps(files, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved:", sorted(p.name for p in out.iterdir()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
