"""Export the whole "test" production READ-ONLY into a lab file (2026-11-13). No model call, nothing written to the database.

    python lab/sable_rows/export_prod.py

Writes `input/test_production.json`: the production, its episodes, every scene (with script and staging, without any
planner's stored result), every shot and dialogue line, and the canon entities with their current card.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLANNER_COLUMNS = ("raphael", "jonathan", "david", "adam", "coverage_plan", "coverage")


def rows(cur: psycopg.Cursor, sql: str, args: tuple = ()) -> list[dict]:
    cur.execute(sql, args)
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def main() -> None:
    with psycopg.connect(dotenv_values(ROOT / ".env")["SUPABASE__DB_URL"], connect_timeout=15) as c:
        c.execute("set transaction read only")
        cur = c.cursor()
        production = rows(cur, "select id, title, settings from productions where title = %s", ("test",))[0]
        pid = production["id"]
        episodes = rows(cur, "select id, number, title, synopsis from episodes where production_id=%s order by number",
                        (pid,))
        scenes = rows(cur, "select * from scenes where production_id=%s order by number", (pid,))
        shots = rows(cur, "select * from shots where production_id=%s order by number", (pid,))
        lines = rows(cur, "select * from dialogue_lines where production_id=%s order by ord", (pid,))
        canon = rows(cur, """select e.id, e.kind, e.code, e.name, e.aliases, v.card from canon_entities e
                             left join canon_versions v on v.id = e.current_version_id where e.production_id=%s
                             order by e.code""", (pid,))
    for s in scenes:
        for k in PLANNER_COLUMNS:
            s.pop(k, None)
    out = {"production": production, "episodes": episodes, "scenes": scenes, "shots": shots, "lines": lines,
           "canon": canon}
    path = HERE / "input" / "test_production.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"{path.name}: {len(episodes)} episodes, {len(scenes)} scenes, {len(shots)} shots, {len(lines)} lines, "
          f"{len(canon)} canon")


if __name__ == "__main__":
    main()
