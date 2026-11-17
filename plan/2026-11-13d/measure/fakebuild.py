"""A simulated structure build for measuring the build page (plan/2026-11-13d section 6). No function runs and no model
is called: this writes a `structure_build` job in the creation walk's production and appends its events with the
service key, the way the worker would, then finishes it. The person chose no more real build walks (IMPLEMENTED.md).

    python fakebuild.py [seconds] [gap]     # default 120 s, an event every 3 s; prints the job id
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import _common  # noqa: E402

_common.load_env()
HERE = Path(__file__).resolve().parent
r = _common.Rest()
H = {**r.h, "Prefer": "return=representation"}
ids = json.loads((HERE / "create.json").read_text(encoding="utf-8"))
P = ids["P"]
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 3
STAGES = ["read", "canon", "episodes", "scenes", "shots", "continuity"]


def post(table: str, row: dict) -> dict:
    res = r.c.post(f"{r.rest}/{table}", headers=H, json=row)
    res.raise_for_status()
    return res.json()[0]


def status(job_id: str, value: str) -> None:
    r.c.patch(f"{r.rest}/jobs", headers=r.h, params={"id": f"eq.{job_id}"}, json={"status": value}).raise_for_status()
    post("job_events", {"job_id": job_id, "type": "status", "payload": {"status": value}})


bot = r.get("profiles", email="eq.traffic-bot@hiru.test", select="id")[0]["id"]
job = post("jobs", {"id": str(uuid.uuid4()), "kind": "structure_build", "status": "running", "production_id": P,
                    "requested_by": bot, "request": {"pipeline": ["structure_build"], "simulated": True}})
print(job["id"], flush=True)
post("job_events", {"job_id": job["id"], "type": "status", "payload": {"status": "running"}})
start = time.time()
n = 0
while time.time() - start < SECONDS:
    stage = STAGES[min(n // 8, len(STAGES) - 1)]
    if n % 8 == 0:
        post("job_events", {"job_id": job["id"], "type": "stage", "payload": {"stage": stage, "state": "active",
                                                                           "text": f"simulated {stage}"}})
    elif n % 8 == 7:
        post("job_events", {"job_id": job["id"], "type": "stage", "payload": {"stage": stage, "state": "done",
                                                                           "text": f"simulated {stage} done"}})
    else:
        post("job_events", {"job_id": job["id"], "type": "agent_step", "agent": "script_architect",
                            "payload": {"text": f"Simulated step {n}"}})
    n += 1
    time.sleep(GAP)
status(job["id"], "done")
print(f"done: {n} events", flush=True)
