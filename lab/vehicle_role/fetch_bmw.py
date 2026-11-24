"""Read the BMW case out of the hosted dev database into `input_bmw/` (read-only: GET requests only).

The case (2026-11-24): Love Hour, scene 6de06ab0, shot 1fc8a283. The canon has a BMW 520d; the person says the shot
does not show it.

    .venv/Scripts/python.exe lab/vehicle_role/fetch_bmw.py
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

PROD = "b89f79a3-3ce6-4123-aee5-759f35c09d69"
SCENE = "6de06ab0-5c93-4c03-bde2-61f6410b1b02"
SHOT = "1fc8a283-d57a-46b0-840e-dd666e475582"


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


def save(name: str, data: object) -> None:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


OUT = HERE / "input_bmw"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    canon = rows("canon_entities", production_id=f"eq.{PROD}",
                 select="*,current:canon_versions!canon_entities_current_version_fkey(*)")
    save("canon.json", canon)
    scene = rows("scenes", id=f"eq.{SCENE}", select="*")
    save("scene.json", scene)
    shots = rows("shots", scene_id=f"eq.{SCENE}", select="*", order="number.asc")
    save("shots.json", shots)
    boards = rows("scene_boards", scene_id=f"eq.{SCENE}", select="*", order="created_at.desc")
    save("boards.json", boards)
    frames = rows("first_frames", shot_id=f"eq.{SHOT}", select="*", order="created_at.desc", limit="3")
    save("frames.json", frames)
    for c in canon:
        if c.get("kind") == "location" and sheet_path(c):
            safe = "".join(ch if ch.isalnum() else "_" for ch in c["name"])[:40]
            try:
                (OUT / f"plate_{safe}.png").write_bytes(file("references", sheet_path(c)))
            except httpx.HTTPError as e:
                print(f"plate {c['name']}: {e}")
    for i, b in enumerate(boards[:4]):
        if b.get("storage_path"):
            (OUT / f"board_{i}_v{b.get('version')}_p{b.get('part')}.png").write_bytes(file("frames", b["storage_path"]))
    for i, f in enumerate(frames):
        if f.get("storage_path") and f.get("status") == "done":
            (OUT / f"frame_{i}.png").write_bytes(file("frames", f["storage_path"]))
    print(f"canon {len(canon)}; scene {len(scene)}; shots {len(shots)}; boards {len(boards)}; frames {len(frames)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
