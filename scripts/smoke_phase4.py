"""Phase 4 end-to-end smoke test: the Production panel.

Scene 1 of the Harbour Lights fixture is seeded as in Phase 3's smoke test and approved by a
director; then, through the real API and the real functions: the panel before anything is
made, a design (`shot_producer`), a person's camera, first frames (`frame_render`), accepting one
to unlock the prompt, a prompt version with the Sinhala line byte for byte, the frame streamed
through `/files/{ticket}`, and staleness after a shot edit and a new canon card.

Without an OpenAI key the design runs by rules and frame_render cannot paint: the frames come
back failed ("not set up"), so the script stands in one placeholder PNG as the function would
have written it, to carry on with accept → prompt. With a key every step is real, and a
reference sheet is painted too.

Needs the API on :8000 and the functions (scripts/start-functions.ps1: shot_producer :8207,
frame_render :8208), schema v3, and an admin. Writes test data to the database it points at.

    python scripts/smoke_phase4.py you@hirutv.lk <admin password>
"""
from __future__ import annotations

import base64
import os
import sys
import time
import uuid
from typing import Any

import httpx
from _common import Rest, load_env

load_env()
from smoke_phase3 import API, check, local_user, seed, sign_in  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=")


def wait(client: httpx.Client, job_id: str, seconds: int = 900) -> dict[str, Any]:
    deadline = time.time() + seconds
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = client.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(2)
    return job


def main(admin_email: str, admin_password: str) -> None:
    started = time.monotonic()
    keyed = bool(os.environ.get("OPENAI__API_KEY"))
    admin = httpx.Client(base_url=API, headers=sign_in(admin_email, admin_password), timeout=120)
    pid = admin.post("/v1/productions", json={"title": f"Phase 4 smoke {uuid.uuid4().hex[:6]}",
                                              "orientation": "horizontal"}).json()["id"]
    tag = uuid.uuid4().hex[:6]
    director = local_user(f"director-{tag}@hirutv.lk", "local-director-123", pid, "director")
    crew = local_user(f"crew-{tag}@hirutv.lk", "local-crew-12345", pid, "production")
    writer = local_user(f"writer-{tag}@hirutv.lk", "local-writer-123", pid, "writer")
    db = Rest()
    s = seed(db, pid)
    base = f"/v1/productions/{pid}"
    scene = f"{base}/scenes/{s['scene']}"
    card = {"gender": "female", "age": "52", "appearance": "grey-streaked hair in a bun",
            "wardrobe": "a faded blue cotton saree", "voice": "low, clipped"}
    r = director.post(f"{base}/canon/{s['kamala']}/versions", json={"card": card})
    check("Kamala has a card (v1) with a voice pin", r.status_code == 201 and r.json()["voice_pin"], r.text)

    # ── before anything is made ──────────────────────────────────────────────────────────
    v = crew.get(f"{scene}/production").json()
    check("panel: four shots, nothing designed, locked until approval",
          len(v["shots"]) == 4 and all(x["design"]["state"] == "missing" and x["prompt_lock"]["locked"]
                                       for x in v["shots"]), v)
    check("design waits for approval (409)", crew.post(f"{scene}/design", json={}).status_code == 409)
    director.post(f"{scene}/approve")
    check("a writer cannot design (403)", writer.post(f"{scene}/design", json={}).status_code == 403)

    # ── design ───────────────────────────────────────────────────────────────────────────
    job = wait(crew, crew.post(f"{scene}/design", json={}).json()["job_id"])
    check("design job finishes", job.get("status") == "done", job)
    v = crew.get(f"{scene}/production").json()
    planner = v["shots"][0]["design"]["planner"]
    check(f"every shot designed ({planner}), current, with a rationale",
          all(x["design"]["state"] == "current" and x["design"]["rationale"] for x in v["shots"]), v["shots"])
    s02 = v["shots"][1]
    check("the director's size wins", s02["camera"]["recommended"]["framing"] == "Medium shot", s02["camera"])
    check("a frame prompt is ready to paint", "Sri Lankan" in s02["frame_prompt"], s02["frame_prompt"][:200])

    # ── a person's camera ────────────────────────────────────────────────────────────────
    r = crew.patch(f"{base}/shots/{s['shots'][1]}/camera", json={"lens": "85mm"})
    check("crew sets S02 to 85mm", r.status_code == 200 and r.json()["camera"]["changed"] == ["lens"], r.text)

    # ── frames ───────────────────────────────────────────────────────────────────────────
    r = crew.post(f"{base}/shots/{s['shots'][1]}/frames", json={"count": 2})
    check("two frames asked for", r.status_code == 202 and len(r.json()["frame_ids"]) == 2, r.text)
    frame_ids = r.json()["frame_ids"]
    job = wait(crew, r.json()["job_id"])
    check("frame job finishes", job.get("status") == "done", job)
    frames = db.get("first_frames", id=f"in.({','.join(frame_ids)})", select="*")
    if keyed:
        check("both frames painted and stored", all(f["status"] == "done" and f["storage_path"] for f in frames),
              [(f["status"], f["error"]) for f in frames])
        check("the frame prompt carries the person's lens", "85mm" in frames[0]["prompt"], frames[0]["prompt"][:300])
    else:
        check("without a key the frames say so", all("not set up" in (f["error"] or "") for f in frames), frames)
        path = f"{pid}/{s['shots'][1]}/{frame_ids[0]}.png"
        db.upload("frames", path, PNG, "image/png")
        pins = db.get("shots", id=f"eq.{s['shots'][1]}", select="design")[0]["design"]["pins"]
        r = db.c.patch(f"{db.rest}/first_frames", headers=db.h, params={"id": f"eq.{frame_ids[0]}"},
                       json={"status": "done", "storage_path": path, "pins": pins, "error": None})
        r.raise_for_status()
    v = crew.get(f"{base}/shots/{s['shots'][1]}").json()
    url = next(f["url"] for f in v["frames"] if f["status"] == "done")
    check("frames are links to this API, never to storage", url.startswith(f"{API}/files/") and "supabase" not in url,
          url)
    got = httpx.get(url, timeout=60)
    check("the frame streams through /files", got.status_code == 200 and got.content[:4] == b"\x89PNG", got.status_code)

    # ── accept → prompt ──────────────────────────────────────────────────────────────────
    check("no prompt before a frame is accepted (409)",
          crew.post(f"{base}/shots/{s['shots'][1]}/prompt").status_code == 409)
    done = next(f["id"] for f in v["frames"] if f["status"] == "done")
    v = crew.post(f"{base}/frames/{done}/accept").json()
    check("accepting unlocks the prompt", v["accepted_frame_id"] == done and not v["prompt_lock"]["locked"]
          and v["status"] == "frame", v["prompt_lock"])
    job = wait(crew, crew.post(f"{base}/shots/{s['shots'][1]}/prompt").json()["job_id"])
    check("prompt job finishes", job.get("status") == "done", job)
    p = crew.get(f"{base}/shots/{s['shots'][1]}/prompt").json()
    line = db.get("dialogue_lines", scene_id=f"eq.{s['scene']}", ord="eq.0", select="text")[0]["text"]
    sinhala = [seg["sinhala"] for sec in p["sections"] for seg in sec["segments"] if "sinhala" in seg]
    check("prompt v1: Nimal's line byte for byte, the person's lens, the accepted frame",
          p["version"] == 1 and sinhala == [line] and "85mm" in p["prose"] and p["frame_id"] == done, p["prose"][:400])
    check("its checks pass", all(c["tone"] != "fail" for c in p["checks"]), p["checks"])
    audit = db.get("audit_log", production_id=f"eq.{pid}", actor_agent="eq.shot_producer", select="action")
    check("the agents' work is in the audit log", {"shots.design", "shots.prompt"} <= {a["action"] for a in audit},
          audit)

    # ── upstream changes are flagged, never redone ───────────────────────────────────────
    director.post(f"{scene}/unapprove")
    director.patch(f"{base}/shots/{s['shots'][1]}", json={"duration_s": 8})
    director.post(f"{scene}/approve")
    v = crew.get(f"{base}/shots/{s['shots'][1]}").json()
    check("a longer S02 makes its design, frame and prompt out of date",
          v["design"]["state"] == "stale" and v["prompt"]["stale"] and v["prompt_lock"]["locked"], v["prompt"])
    check("prompt v1 is still there, unchanged", crew.get(f"{base}/shots/{s['shots'][1]}/prompts").json()[0]["version"]
          == 1)
    director.post(f"{base}/canon/{s['kamala']}/versions", json={"card": {**card, "wardrobe": "a green saree"}})
    v = crew.get(f"{scene}/production").json()
    check("Kamala's new card flags the shots she is in",
          v["shots"][3]["design"]["state"] == "stale"
          and any("new card" in r for r in v["shots"][3]["design"]["stale_reasons"]), v["shots"][3]["design"])

    if keyed:
        job = wait(director, director.post(f"{base}/canon/{s['kamala']}/reference-sheet").json()["job_id"])
        entity = director.get(f"{base}/canon/{s['kamala']}").json()
        check("a reference sheet for Kamala's current card", job.get("status") == "done"
              and entity["reference_sheet_url"].startswith(f"{API}/files/"), job)
    print(f"\nPhase 4 smoke passed in {time.monotonic() - started:.0f} s ({'with' if keyed else 'without'} OpenAI).")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python scripts/smoke_phase4.py <admin email> <admin password>")
    main(sys.argv[1], sys.argv[2])
