"""Join browser.jsonl (what the browser asked) with trace.jsonl (what each API request did in the DB) -> report.txt.

    python analyze.py            # prints and writes report.txt
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
browser = [json.loads(x) for x in (HERE / "browser.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
trace = [json.loads(x) for x in (HERE / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

steps = [(b["at"], b["step"]) for b in browser if b["ev"] == "step"]


def step_at(t: float) -> str:
    name = "before"
    for at, s in steps:
        if t >= at:
            name = s
    return name


def norm(u: str) -> str:
    return ID.sub("{id}", u.split("?")[0])


for t in trace:
    t["step"] = step_at(t["at"] - t["ms"] / 1000)

out = []
p = out.append
p("# Per step: browser->API requests, DB queries made by them\n")
p(f"{'step':28} {'api':>4} {'dupAPI':>6} {'db':>4} {'ms(sum)':>8}  top routes")
by_step = defaultdict(list)
for t in trace:
    by_step[t["step"]].append(t)
breq = defaultdict(list)
for b in browser:
    if b["ev"] == "req" and not b["url"].startswith("SB"):
        breq[b["step"]].append(b)
for _, s in steps:
    rows = by_step.get(s, [])
    reqs = breq.get(s, [])
    dup = sum(c - 1 for c in Counter((b["method"], b["url"]) for b in reqs).values() if c > 1)
    routes = Counter(f"{r['method']} {norm(r['path'])}" for r in rows)
    top = ", ".join(f"{k.split(' ', 1)[1].replace('/v1/productions/{id}', '')}x{v}" for k, v in routes.most_common(4))
    p(f"{s:28} {len(rows):>4} {dup:>6} {sum(r['db'] for r in rows):>4} {sum(r['ms'] for r in rows):>8.0f}  {top}")

p("\n# Same API URL requested more than once inside one step (redundant fetches)\n")
for _, s in steps:
    c = Counter((b["method"], ID.sub("{id}", b["url"])[:140]) for b in breq.get(s, []))
    for (m, u), n in c.items():
        if n > 1:
            p(f"  {s:26} {n}x {m} {u}")

p("\n# Routes: calls, DB queries per call (min/avg/max), time\n")
agg = defaultdict(list)
for t in trace:
    agg[f"{t['method']} {norm(t['path'])}"].append(t)
p(f"{'route':78} {'calls':>5} {'db min/avg/max':>16} {'avg ms':>7}")
for k, rows in sorted(agg.items(), key=lambda kv: -sum(r["db"] for r in kv[1])):
    dbs = [r["db"] for r in rows]
    p(f"{k[:78]:78} {len(rows):>5} {min(dbs):>4}/{sum(dbs)/len(dbs):>5.1f}/{max(dbs):>4} {sum(r['ms'] for r in rows)/len(rows):>7.0f}")

p("\n# Identical DB query repeated INSIDE one request (route: query xN)\n")
seen = Counter()
for t in trace:
    c = Counter((q["m"], q["t"], q["q"]) for q in t["queries"])
    for (m, tb, q), n in c.items():
        if n > 1:
            seen[(f"{t['method']} {norm(t['path'])}", m, tb, ID.sub("{id}", q)[:160], n)] += 1
for (route, m, tb, q, n), times in seen.most_common(40):
    p(f"  {route}  ->  {m} {tb}?{q}  x{n}  (in {times} requests)")

p("\n# Tables hit per request (same table read several times in one request)\n")
seen2 = Counter()
for t in trace:
    c = Counter((q["m"], q["t"]) for q in t["queries"] if q["m"] == "GET")
    many = {k: v for k, v in c.items() if v >= 3}
    if many:
        seen2[(f"{t['method']} {norm(t['path'])}", tuple(sorted(f"{tb}x{v}" for (m, tb), v in many.items())))] += 1
for (route, tbs), n in seen2.most_common(25):
    p(f"  {route}  ({n} req): {', '.join(tbs)}")

p("\n# Every request's query sequence, one example per route\n")
done = set()
for t in trace:
    k = f"{t['method']} {norm(t['path'])}"
    if k in done:
        continue
    done.add(k)
    p(f"## {k}  db={t['db']} ms={t['ms']}")
    for q in t["queries"]:
        p(f"   {q['m']:5} {q['t']:28} {ID.sub('{id}', q['q'])[:150]}  {q.get('ms', '')}ms {q.get('cr', '')}")

p("\n# Query patterns across the whole run (table + filter shape)\n")
shape = Counter()
for t in trace:
    for q in t["queries"]:
        shape[(q["m"], q["t"], re.sub(r"=([a-z]+)\.[^&]*", r"=\1.?", ID.sub("{id}", q["q"]))[:150])] += 1
for (m, tb, q), n in shape.most_common(40):
    p(f"  {n:>5} {m:5} {tb:24} {q}")

p("\n# Errors / non-2xx\n")
for t in trace:
    if t["status"] >= 400:
        p(f"  {t['status']} {t['method']} {t['path']} step={t['step']}")
for b in browser:
    if b["ev"] in ("console", "pageerror", "nav-error", "no-link"):
        p(f"  [{b['step']}] {b['ev']}: {b.get('text') or b.get('shot') or b.get('scene')}")

p("\n# Browser -> Supabase directly\n")
for k, v in Counter((b["step"], b["method"], ID.sub("{id}", b["url"])[:120]) for b in browser
                    if b["ev"] == "req" and b["url"].startswith("SB")).most_common(30):
    p(f"  {v}x {k}")

totals = (len(trace), sum(t["db"] for t in trace))
p(f"\nTOTAL api requests={totals[0]} db queries={totals[1]}")
text = "\n".join(out)
(HERE / "report.txt").write_text(text, encoding="utf-8")
print(text[: int(sys.argv[1]) if len(sys.argv) > 1 else 10**9])
