"""Read-only: every dialogue line in the database with its shot, longest first. GET only."""
from __future__ import annotations
import json, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "portrait_board"))
from fetch import Rest  # noqa: E402

rest = Rest()
prods = {p["id"]: p for p in rest.rows("productions", {"select": "id,title,created_at,settings"})}
lines = rest.rows("dialogue_lines", {"select": "id,production_id,scene_id,shot_id,ord,speaker,text,delivery,words,overrun_s,source_lang", "limit": "5000"})
shot_ids = sorted({l["shot_id"] for l in lines if l["shot_id"]})
shots = {}
for i in range(0, len(shot_ids), 80):
    for s in rest.rows("shots", {"id": f"in.({','.join(shot_ids[i:i+80])})", "select": "id,number,duration_s,duration_locked,planner,sound_mode"}):
        shots[s["id"]] = s
print("productions:")
for p in prods.values():
    st = p.get("settings") or {}
    print(" ", p["id"][:8], p["title"], p["created_at"][:10], "max_take_s", st.get("max_take_s"), st.get("take_lengths"))
print("lines", len(lines), "by production", Counter(prods.get(l["production_id"], {}).get("title") for l in lines))
rows = []
for l in lines:
    s = shots.get(l["shot_id"]) or {}
    rows.append({**l, "prod": prods.get(l["production_id"], {}).get("title"), "shot_n": s.get("number"),
                 "shot_s": s.get("duration_s"), "planner": s.get("planner"), "lines_in_shot": 0})
per_shot = Counter(l["shot_id"] for l in lines if l["shot_id"])
for r in rows:
    r["lines_in_shot"] = per_shot.get(r["shot_id"], 0)
rows.sort(key=lambda r: -(r["words"] or 0))
(HERE / "lines.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
print("words histogram", sorted(Counter(r["words"] for r in rows).items()))
print("overrun lines", sum(1 for r in rows if (r["overrun_s"] or 0) > 0))
for r in rows[:25]:
    print(r["prod"], "shot", r["shot_n"], f"{r['shot_s']}s", "x", r["lines_in_shot"], r["words"], "w", f"over {r['overrun_s']}", repr(r["delivery"][:20]), r["text"][:90])
