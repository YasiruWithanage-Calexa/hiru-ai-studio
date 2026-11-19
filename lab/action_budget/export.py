"""Action-budget lab (2026-11-18), step 1: gather every Raphael clip we have into runs/corpus.json.

    python lab/action_budget/export.py        free: reads the database (read-only) and saved lab plans

Sources:
- `shots` rows with planner = 'raphael' (every production), their `ir.beats` as Raphael wrote them;
- saved Raphael results in the lab (`lab/llm_reader/runs/e2e/12_raphael`, `lab/coverage/runs/coverage/12_raphael`),
  so the plans the person has already judged are in the corpus even where they are not in the database.
Nothing is written to the database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "runs" / "corpus.json"
LAB_PLANS = {
    "lab e2e (Api Denna v2)": ROOT / "lab" / "llm_reader" / "runs" / "e2e" / "12_raphael",
    "lab coverage (Api Denna v2)": ROOT / "lab" / "coverage" / "runs" / "coverage" / "12_raphael",
}


def db_url() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("SUPABASE__DB_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("SUPABASE__DB_URL missing in .env")


def from_db() -> list[dict[str, Any]]:
    import psycopg

    rows: list[dict[str, Any]] = []
    with psycopg.connect(db_url()) as c, c.cursor() as cur:
        cur.execute(
            """select p.title, sc.heading, s.id, s.slate, s.number, s.stage, s.priority, s.role, s.framing,
                      s.duration_s, s.ir, s.intent
               from shots s join productions p on p.id = s.production_id join scenes sc on sc.id = s.scene_id
               where s.planner = 'raphael' order by p.title, sc.heading, s.number"""
        )
        for title, heading, sid, slate, number, stage, priority, role, framing, dur, ir, intent in cur.fetchall():
            ir = ir or {}
            rows.append({
                "source": "db", "production": title, "scene": heading, "id": str(sid), "slate": slate or f"#{number}",
                "stage": stage, "priority": priority, "role": role, "size": framing, "take_s": float(dur or 0),
                "beats": [{"action": b.get("action", ""), "performance": b.get("performance", "")}
                          for b in ir.get("beats") or []],
                "subjects": [s.get("action", "") for s in ir.get("subjects") or []],
                "summary": (intent or {}).get("what_we_see", ""),
            })
    return rows


def from_lab() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, folder in LAB_PLANS.items():
        for f in sorted(folder.glob("*.json")):
            result = json.loads(f.read_text(encoding="utf-8")).get("result") or {}
            for clip in result.get("clips") or []:
                ir = clip.get("ir") or {}
                rows.append({
                    "source": "lab", "production": label, "scene": f.stem, "id": f"{label}/{f.stem}/{clip.get('id')}",
                    "slate": clip.get("slate", ""), "stage": 2 if str(clip.get("id", "")).startswith("x") else 1,
                    "priority": clip.get("priority"), "role": clip.get("role"), "size": clip.get("size"),
                    "take_s": float(clip.get("take_s") or 0),
                    "beats": [{"action": b.get("action", ""), "performance": b.get("performance", "")}
                              for b in ir.get("beats") or []],
                    "subjects": [s.get("action", "") for s in ir.get("subjects") or []],
                    "summary": clip.get("summary", ""),
                })
    return rows


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rows = from_db() + from_lab()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(rows)} clips -> {OUT}")


if __name__ == "__main__":
    main()
