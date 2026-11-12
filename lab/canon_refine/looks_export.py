"""Looks lab: export a production that has NO breakdown memory (built before it) from today's tables, READ-ONLY.

Episodes (title, synopsis), scenes in page order with their script (action text and spoken lines with speakers),
and the current canon cards. Writes `<out>/export.json`. No model call.

    python lab/canon_refine/looks_export.py <production id> <out dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import psycopg
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def rows(cur: Any, sql: str, *args: Any) -> list[dict[str, Any]]:
    cur.execute(sql, args)
    names = [d.name for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def main() -> None:
    production, out = sys.argv[1], Path(sys.argv[2])
    url = dotenv_values(ROOT / ".env")["SUPABASE__DB_URL"]
    with psycopg.connect(str(url)) as c:
        c.execute("set transaction read only")
        cur = c.cursor()
        title = rows(cur, "select title from productions where id=%s", production)[0]["title"]
        episodes = rows(cur, "select number, title, synopsis from episodes where production_id=%s order by number",
                        production)
        scenes = rows(cur, """
            select s.id::text, ep.number as episode, s.number, s.heading, s.title, s.time_of_day, s.script,
                   ce.name as place
            from scenes s join episodes ep on ep.id = s.episode_id left join canon_entities ce on ce.id = s.location_id
            where s.production_id=%s order by ep.number, s.number""", production)
        lines = rows(cur, "select id::text, scene_id::text, speaker, text from dialogue_lines where production_id=%s",
                     production)
        canon = rows(cur, """
            select e.code, e.kind, e.name, e.locked, v.source, v.card
            from canon_entities e left join canon_versions v on v.id = e.current_version_id
            where e.production_id=%s and e.kind='character' order by e.code""", production)
    by_id = {ln["id"]: ln for ln in lines}
    for s in scenes:
        text = []
        for b in s.pop("script") or []:
            if b.get("kind") == "dialogue" and b.get("line_id") in by_id:
                ln = by_id[b["line_id"]]
                text.append(f"{ln['speaker']}: {ln['text']}")
            elif b.get("text"):
                text.append(str(b["text"]))
        s["script"] = text
        s["key"] = f"E{s['episode']:02d}-S{s['number']:02d}"
    data = {"production_id": production, "title": title, "episodes": episodes, "scenes": scenes, "people": canon}
    out.mkdir(parents=True, exist_ok=True)
    (out / "export.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{title}: {len(episodes)} episodes, {len(scenes)} scenes, {len(canon)} characters -> {out / 'export.json'}")


if __name__ == "__main__":
    main()
