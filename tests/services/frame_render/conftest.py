from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "frame_render"))

from frame_render.engine.image import Picture, Reference, RefusedError  # noqa: E402

from tests.services.production_fixture import CANON, PID, fixture_scene  # noqa: E402

DESIGN_IR = {"setting": "Kamala's kitchen at dawn", "lighting": "Firelight from the left.",
             "beats": [{"time": "0-3s", "camera": "", "director_line": "", "action": "stirs"}],
             "first_frame": {"composition": "Kamala at the stove, back to the door", "subjects": ["Kamala"],
                             "setting": "the kitchen", "lighting": "firelight"}}
RECOMMENDED = {"framing": "Wide shot", "angle": "Eye level", "lens": "28mm", "aperture": "f/4",
               "movement": "Static", "speed": "None", "axis": "Side A · left to right",
               "lighting": "Dawn, soft ambient"}


def canon_with_sheets() -> list[dict]:
    canon = copy.deepcopy(CANON)
    canon[0]["current"].update(id=str(uuid4()), reference_assets=[{"path": "p/kamala.png"}])  # Kamala
    canon[2]["current"].update(id=str(uuid4()), reference_assets=["p/house.png"])  # the house (old shape)
    canon[1]["current"].update(id=str(uuid4()), reference_assets=[])
    return canon


class FakeStore:
    def __init__(self, *, orientation: str = "horizontal", design: bool = True) -> None:
        self.scene_row, self.line_rows, shots = fixture_scene(0)
        for s in shots:
            s.update(ir=DESIGN_IR if design else {}, design={"recommended": RECOMMENDED} if design else {},
                     camera_overrides={})
        self.shot_rows = {s["id"]: s for s in shots}
        self.canon_rows = canon_with_sheets()
        self.orientation = orientation
        self.frame_rows: dict[str, dict] = {}
        self.uploads: dict[tuple[str, str], bytes] = {}
        self.audits: list[dict] = []
        self.unreadable: set[str] = set()
        self.asset_writes: list[tuple[str, list]] = []
        self.look_rows: dict[str, dict] = {}
        self.look_writes: list[tuple[str, list]] = []
        self.scene_look_rows: list[dict] = []  # entity_id, look_id: the scene's picks
        self.episode = 1

    def add_frame(self, shot_id: str, status: str = "queued") -> str:
        fid = str(uuid4())
        self.frame_rows[fid] = {"id": fid, "production_id": str(PID), "shot_id": shot_id, "status": status}
        return fid

    def production(self, production_id: UUID) -> dict | None:
        return {"id": str(production_id), "title": "Harbour Lights", "orientation": self.orientation}

    def frames(self, production_id: UUID, frame_ids: list[str]) -> list[dict]:
        return [dict(self.frame_rows[f]) for f in frame_ids if f in self.frame_rows]

    def shot(self, shot_id: str) -> dict | None:
        return self.shot_rows.get(shot_id)

    def scene(self, scene_id: str) -> dict | None:
        return self.scene_row

    def lines(self, scene_id: str) -> list[dict]:
        return self.line_rows

    def canon(self, production_id: UUID) -> list[dict]:
        return self.canon_rows

    def look(self, look_id: str) -> dict | None:
        return self.look_rows.get(look_id)

    def looks(self, production_id: UUID) -> list[dict]:
        return list(self.look_rows.values())

    def scene_looks(self, scene_id: str) -> list[dict]:
        return self.scene_look_rows

    def episode_number(self, episode_id: str) -> int | None:
        return self.episode

    def download_reference(self, path: str) -> bytes:
        if path in self.unreadable:
            raise OSError("gone")
        return f"sheet:{path}".encode()

    def claim_frame(self, frame_id: str) -> bool:
        row = self.frame_rows[frame_id]
        if row["status"] != "queued":
            return False
        row["status"] = "running"
        return True

    def finish_frame(self, frame_id: str, fields: dict) -> None:
        self.frame_rows[frame_id].update(fields)

    def upload(self, bucket: str, path: str, data: bytes, mime: str) -> None:
        self.uploads[(bucket, path)] = data

    def add_reference_asset(self, version_id: str, assets: list[Any]) -> None:
        self.asset_writes.append((version_id, assets))

    def finish_look_sheet(self, look_id: str, assets: list[Any]) -> None:
        self.look_writes.append((look_id, assets))
        self.look_rows[look_id].update(sheet_assets=assets, status="draft")

    def audit(self, row: dict) -> None:
        self.audits.append(row)


class FakePainter:
    def __init__(self, refuse: bool = False, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.refuse, self.fail = refuse, fail

    def __call__(self, prompt: str, aspect: str, references: list[Reference]) -> Picture:
        self.calls.append({"prompt": prompt, "aspect": aspect, "references": [r.label for r in references],
                           "pictures": [r.data for r in references]})
        if self.refuse:
            raise RefusedError("The image model declined to make this frame.")
        if self.fail:
            raise RuntimeError("provider exploded with internal details")
        return Picture(data=b"\x89PNG fake", mime="image/png", input_tokens=10, output_tokens=20)
