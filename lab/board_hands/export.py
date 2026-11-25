"""plan/2026-11-25 B0: save Scene board v21's ten panels exactly as the board check saw them (read-only: GET requests
only; no model call).

Each case is what `frame_render.board._check_panel` sends `board_inspector`: the panel's own picture (a sheet cell cut
by its `box`, a cell painted again alone from its own `path`), `people`, `panel`, `hands`, and the view it names cut
from the location's views sheet. The labels are the person's look at v21 (2026-11-25), confirmed panel by panel.

    .venv/Scripts/python.exe lab/board_hands/export.py

Writes `lab/board_hands/input/` (`shot_<n>.png`, `shot_<n>_view.png`, `cases.json`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "fixed_marks"), str(ROOT / "src" / "libs")]

import fetch  # noqa: E402  (the fixed-marks lab's read-only helper: the hosted dev database, GET only)

from contracts import board as kit  # noqa: E402
from contracts.canon import views_asset  # noqa: E402
from hiru_ai.systems.frame_render import pictures as pics  # noqa: E402

VERSION = 21
# shot → (label, what is wrong, the part whose cell is used). Shot 11 is painted in part 2 (panel 6, painted again
# alone) and carried into part 3 as the overlap: part 2's is the one the check looked at.
LABELS: dict[int, tuple[str, str, int]] = {
    4: ("bad", "blue: three hands (umbrella at chest, phone at waist, a third arm hanging empty at the hip)", 1),
    5: ("bad", "blue: three hands (umbrella at chest, phone held out, a third arm hanging at the hip)", 1),
    7: ("bad", "blue: umbrella canopy floating with no shaft into a hand; a loose white stick in the other hand", 2),
    8: ("bad", "blue: three or four hands (phone at ear, a fist at the elbow, a hand flat on the chest)", 2),
    1: ("good", "", 1),
    3: ("good", "", 1),
    10: ("good", "", 2),
    11: ("good", "", 2),
    12: ("good", "", 3),
    13: ("good", "", 3),
}


def main() -> int:
    rows = [r for r in fetch.rows("scene_boards", scene_id=f"eq.{fetch.SCENE}", select="*", order="part.asc")
            if r["version"] == VERSION]
    by_part = {r["part"]: r for r in rows}
    writer = kit.Writer.of(rows[0]["writer"])
    colours = dict(rows[0]["colours"] or {})
    canon = fetch.rows("canon_entities", production_id=f"eq.{fetch.PROD}",
                       select="id,name,kind,current:canon_versions!canon_entities_current_version_fkey(*)")
    names = {str(c["id"]): c["name"] for c in canon}
    colours = {names.get(k, k): v for k, v in colours.items()}  # the board stores colours by canon id
    scene = fetch.rows("scenes", id=f"eq.{fetch.SCENE}", select="location_id")[0]
    location = next(c for c in canon if str(c["id"]) == str(scene["location_id"]))
    asset = views_asset(location)
    views = [dict(v) for v in (asset or {}).get("views") or []]
    sheet = fetch.file("references", str(asset["path"])) if asset else b""
    out = HERE / "input"
    out.mkdir(exist_ok=True)
    boards: dict[int, bytes] = {}
    cases = []
    for shot, (label, fault, part) in LABELS.items():
        row = by_part[part]
        cell = next(c for c in row["cells"] if c.get("number") == shot and c.get("panel"))
        if cell.get("box"):
            if part not in boards:
                boards[part] = fetch.file("frames", row["storage_path"])
            data = pics.crop(boards[part], cell["box"])
        else:
            data = fetch.file("frames", cell["path"])
        (out / f"shot_{shot}.png").write_bytes(data)
        panel = writer.panel(shot)
        assert panel is not None, shot
        view = kit.panel_view(panel, kit.views_of(panel, views, {}))
        case = {"shot": shot, "label": label, "fault": fault, "part": part, "source": cell.get("source"),
                "saved_check": cell.get("check"),
                "input": {"mime": "image/png",
                          "people": [f"{n} is the {c} mannequin" for n, c in colours.items()
                                     if any(x.name == n for x in panel.people)],
                          "panel": f"{panel.camera.rstrip('.')}. {panel.picture}",
                          "hands": kit.hands_text(panel, colours)}}
        if view is not None and view.get("box") and sheet:
            (out / f"shot_{shot}_view.png").write_bytes(pics.crop(sheet, [int(x) for x in view["box"]]))
            case["input"]["view"] = kit.view_named(view)
        cases.append(case)
        print(shot, label, cell.get("source"), len(data), "view" if "view" in case["input"] else "no view")
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
