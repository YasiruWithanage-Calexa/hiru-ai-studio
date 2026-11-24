"""Read the people sheets for the BMW case's shot 1 frame into `input_bmw/` (read-only: GET requests only):
Anudi's face sheet and her look sheet in this scene, the driver's face sheet and character sheet.

    .venv/Scripts/python.exe lab/vehicle_role/fetch_bmw_people.py
"""
from __future__ import annotations

import json
import sys

from fetch_bmw import OUT, SCENE, file, rows  # read-only helpers of the scene fetch

sys.path[:0] = []

from contracts.canon import face_sheet_path, look_sheet_path  # noqa: E402
from contracts.frame_brief import sheet_path  # noqa: E402

PEOPLE = {"C02": "anudi", "C05": "driver"}


def main() -> int:
    canon = json.loads((OUT / "canon.json").read_text(encoding="utf-8"))
    picks = {p["entity_id"]: p["look_id"] for p in rows("scene_looks", scene_id=f"eq.{SCENE}",
                                                          select="entity_id,look_id")}
    got = {}
    for row in canon:
        short = PEOPLE.get(str(row.get("code")))
        if not short:
            continue
        (OUT / f"{short}_face.png").write_bytes(file("references", face_sheet_path(row)))
        (OUT / f"{short}_sheet.png").write_bytes(file("references", sheet_path(row)))
        got[short] = ["face", "sheet"]
        look_id = picks.get(row["id"])
        if look_id:
            look = rows("canon_looks", id=f"eq.{look_id}", select="*")[0]
            (OUT / f"{short}_look.json").write_text(json.dumps(look, ensure_ascii=False, indent=1, default=str),
                                                     encoding="utf-8")
            if look_sheet_path(look):
                (OUT / f"{short}_look.png").write_bytes(file("references", look_sheet_path(look)))
                got[short].append("look")
    print(got)
    return 0


if __name__ == "__main__":
    sys.exit(main())
