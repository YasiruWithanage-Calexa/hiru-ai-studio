"""Read a run's clips: which show the phone, at which line. No model call."""
import json, re, sys
for d in sys.argv[1:]:
    j = json.load(open(f"{d}/12_raphael/E01-S02.json", encoding="utf-8"))
    r = j["result"]
    print(f"\n=== {d.split('/')[-1]}  ${j['dollars']}  seconds {r.get('seconds')}")
    for c in r.get("clips", []):
        s = c.get("summary", "")
        hit = re.search(r"\b(phone|handset|caller|screen)\b", s, re.I)
        if hit or c.get("role") == "insert":
            print(f"  {c['id']} {c.get('size')} {c.get('role')} {c.get('priority')}: {s[:200]}")
    for x in r.get("review", []):
        if re.search(r"phone|device|record|playback|call", x["why"], re.I):
            print(f"  review m{x['moment']} earns={x['earns']}: {x['why'][:200]}")
