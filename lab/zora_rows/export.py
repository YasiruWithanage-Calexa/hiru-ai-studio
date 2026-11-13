"""Export one scene's rows from the dev database, READ-ONLY, into lab files (plan/2026-11-12d phase 0). No model call.

    python lab/zora_rows/export.py [scene_id]

Writes `input/<scene_id>.json`: the scene row (without the planners' stored results, which Zora must not read), its
shot rows, its dialogue lines, the production's characters and the staging map. Nothing is written to the database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCENE = "0f4ba0fd-db0b-4722-8feb-e89586b06f24"  # Hiru Short Combined 2, Scene 03, Colombo garage (Raphael)
PLANNER_COLUMNS = ("raphael", "jonathan", "david", "adam", "coverage_plan")  # never handed to Zora


def rows(cur: psycopg.Cursor, sql: str, args: tuple) -> list[dict]:
    cur.execute(sql, args)
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def main(scene_id: str) -> None:
    url = dotenv_values(ROOT / ".env")["SUPABASE__DB_URL"]
    with psycopg.connect(url) as c:
        c.execute("set transaction read only")
        cur = c.cursor()
        scene = rows(cur, "select * from scenes where id=%s", (scene_id,))[0]
        shots = rows(cur, "select * from shots where scene_id=%s order by number", (scene_id,))
        lines = rows(cur, "select * from dialogue_lines where scene_id=%s order by ord", (scene_id,))
        chars = rows(cur, "select id, code, name, kind from canon_entities where production_id=%s and kind='character'",
                     (scene["production_id"],))
        prod = rows(cur, "select id, title, settings from productions where id=%s", (scene["production_id"],))[0]
    for k in PLANNER_COLUMNS:
        scene.pop(k, None)
    out = {"production": prod, "scene": scene, "shots": shots, "lines": lines, "characters": chars}
    path = HERE / "input" / f"{scene_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{path.name}: {len(shots)} shots, {len(lines)} lines, {len(chars)} characters")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else SCENE)
