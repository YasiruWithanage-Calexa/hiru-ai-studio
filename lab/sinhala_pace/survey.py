"""Read-only: which existing takes carry dialogue, and how much. GET only."""
from __future__ import annotations
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "portrait_board"))
from fetch import Rest  # noqa: E402

rest = Rest()
takes = rest.rows("takes", {"select": "id,shot_id,duration_s,status,bytes,storage_path,created_at", "limit": "1000"})
renders = rest.rows("video_renders", {"select": "take_id,model,spec->>resolution,status", "limit": "2000"})
by_take = {r["take_id"]: r for r in renders if r.get("take_id")}
shot_ids = sorted({t["shot_id"] for t in takes})
shots, lines = {}, []
for i in range(0, len(shot_ids), 80):
    chunk = ",".join(shot_ids[i:i+80])
    for s in rest.rows("shots", {"id": f"in.({chunk})", "select": "id,production_id,scene_id,number,duration_s,sound_mode,words,planner"}):
        shots[s["id"]] = s
    lines += rest.rows("dialogue_lines", {"shot_id": f"in.({chunk})", "select": "shot_id,ord,speaker,text,delivery,words,source_lang,start_s"})
print("takes", len(takes), "shots with takes", len(shot_ids), "lines on them", len(lines))
spoken = {l["shot_id"] for l in lines}
rows = []
for t in takes:
    s = shots.get(t["shot_id"]) or {}
    ls = sorted([l for l in lines if l["shot_id"] == t["shot_id"]], key=lambda l: l["ord"])
    r = by_take.get(t["id"]) or {}
    rows.append({"take": t["id"], "shot": t["shot_id"], "prod": s.get("production_id"), "n": s.get("number"),
                 "shot_s": s.get("duration_s"), "take_s": t["duration_s"], "status": t["status"],
                 "model": r.get("model"), "res": r.get("resolution"), "mode": s.get("sound_mode"),
                 "path": t["storage_path"], "lines": [{k: l[k] for k in ("speaker", "text", "delivery", "words", "start_s")} for l in ls]})
(HERE / "survey.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
withl = [r for r in rows if r["lines"]]
print("takes with dialogue", len(withl))
from collections import Counter
print(Counter((r["model"], r["res"]) for r in withl))
print(Counter(r["prod"] for r in withl))
