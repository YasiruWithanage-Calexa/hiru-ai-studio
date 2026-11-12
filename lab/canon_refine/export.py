"""Canon refine lab (2026-11-12): export one production's breakdown memory, source memories and canon, READ-ONLY.

No model call, no write: the transaction is read only. Writes `<out>/export.json`.

    python lab/canon_refine/export.py [production id] [out dir]
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
EKAMA = "96c4a5b7-b00e-44e1-acb8-f3ec75241a23"


def rows(cur: Any, sql: str, *args: Any) -> list[dict[str, Any]]:
    cur.execute(sql, args)
    names = [d.name for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def main() -> None:
    production = sys.argv[1] if len(sys.argv) > 1 else EKAMA
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "ekama"
    url = dotenv_values(ROOT / ".env")["SUPABASE__DB_URL"]
    with psycopg.connect(str(url)) as c:
        c.execute("set transaction read only")
        cur = c.cursor()
        memory = rows(cur, "select body, version from breakdown_memories where production_id=%s", production)
        sources = rows(cur, "select document_id, filename, body from source_memories where production_id=%s "
                            "order by created_at, document_id", production)
        canon = rows(cur, """
            select e.id::text, e.kind, e.code, e.name, e.aliases, e.locked, v.version, v.source, v.card
            from canon_entities e left join canon_versions v on v.id = e.current_version_id
            where e.production_id=%s order by e.kind, e.code""", production)
        looks = rows(cur, """
            select l.entity_id::text, l.name, l.status, l.outfit, l.hair, l.makeup, l.accessories, l.ranges
            from canon_looks l join canon_entities e on e.id = l.entity_id where e.production_id=%s""", production)
        scenes = rows(cur, """
            select s.id::text, ep.number as episode, s.number, s.heading, s.location_id::text
            from scenes s join episodes ep on ep.id = s.episode_id where s.production_id=%s order by 2, 3""",
                      production)
    if not memory:
        raise SystemExit("This production has no breakdown memory.")
    data = {"production_id": production, "memory": memory[0]["body"], "memory_version": memory[0]["version"],
            "sources": sources, "canon": canon, "looks": looks, "scenes": scenes}
    out.mkdir(parents=True, exist_ok=True)
    (out / "export.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"exported {len(canon)} canon entries, {len(data['memory']['entities'])} breakdown entities, "
          f"{len(scenes)} scenes -> {out / 'export.json'}")


if __name__ == "__main__":
    main()
