"""The creation walk's numbers per stretch (plan/2026-11-13d section 6).

    python analyze.py <label>     # reads browser.<label>.jsonl and the part of trace.jsonl inside its time window,
                                  # writes report.<label>.txt
Columns: api = requests the API served (OPTIONS apart), from_browser = of those, asked by the browser (the rest are
server renders), options = CORS preflights, db = queries, kb = response bytes.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
label = sys.argv[1] if len(sys.argv) > 1 else "run"
browser = [json.loads(x) for x in (HERE / f"browser.{label}.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
t0, t1 = browser[0]["at"] - 1, browser[-1]["at"] + 5
trace = [json.loads(x) for x in (HERE / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
trace = [t for t in trace if t0 <= t["at"] <= t1]
steps = [(b["at"], b["step"]) for b in browser if b["ev"] == "step"]


def step_at(t: float) -> str:
    name = "before"
    for at, s in steps:
        if t >= at:
            name = s
    return name


def norm(u: str) -> str:
    return ID.sub("{id}", u.split("?")[0]).replace("/v1/productions/{id}", "")


for t in trace:
    t["step"] = step_at(t["at"] - t["ms"] / 1000)
first = {s: at for at, s in reversed(steps)}
nxt = {s: (steps[i + 1][0] if i + 1 < len(steps) else t1) for i, (_, s) in enumerate(steps)}

out: list[str] = []
p = out.append
p(f"# Creation walk '{label}': per stretch\n")
p(f"{'step':18} {'secs':>5} {'api':>4} {'browser':>7} {'options':>7} {'db':>4} {'kb':>6}  top routes")
tot = Counter()
for _, s in steps:
    rows = [t for t in trace if t["step"] == s]
    calls = [t for t in rows if t["method"] != "OPTIONS"]
    opts = len(rows) - len(calls)
    from_browser = sum(1 for b in browser if b["step"] == s and b["ev"] == "req" and not b["url"].startswith("SB"))
    db = sum(t["db"] for t in rows)
    kb = sum(t.get("bytes", 0) for t in rows) / 1024
    top = Counter(f"{norm(t['path'])}" for t in calls).most_common(5)
    secs = nxt[s] - first[s]
    p(f"{s:18} {secs:>5.0f} {len(calls):>4} {from_browser:>7} {opts:>7} {db:>4} {kb:>6.1f}  "
      + ", ".join(f"{k}x{v}" for k, v in top))
    tot.update(api=len(calls), browser=from_browser, options=opts, db=db, kb=kb)
p(f"{'TOTAL':18} {'':>5} {tot['api']:>4} {tot['browser']:>7} {tot['options']:>7} {tot['db']:>4} {tot['kb']:>6.1f}")

p("\n# Routes: calls, DB queries per call (min/avg/max), bytes per call\n")
agg = defaultdict(list)
for t in trace:
    agg[f"{t['method']} {norm(t['path'])}"].append(t)
for k, rows in sorted(agg.items(), key=lambda kv: -sum(r["db"] for r in kv[1])):
    dbs = [r["db"] for r in rows]
    p(f"  {k[:70]:70} {len(rows):>4}x  db {min(dbs)}/{sum(dbs) / len(dbs):.1f}/{max(dbs)}  "
      f"{sum(r.get('bytes', 0) for r in rows) / len(rows) / 1024:.1f} kb")

p("\n# OPTIONS preflights per URL (a browser with a working preflight cache sends one per URL per 10 min)\n")
for u, n in Counter(norm(t["path"]) for t in trace if t["method"] == "OPTIONS").most_common(15):
    p(f"  {n:>3}x {u}")

p("\n# Errors\n")
for t in trace:
    if t["status"] >= 400:
        p(f"  {t['status']} {t['method']} {norm(t['path'])} step={t['step']}")
for b in browser:
    if b["ev"] in ("console", "pageerror", "nav-error", "no-link", "timeout"):
        p(f"  [{b['step']}] {b['ev']}: {b.get('text', '')[:200]}")

text = "\n".join(out)
(HERE / f"report.{label}.txt").write_text(text, encoding="utf-8")
print(text)
