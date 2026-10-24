"""Phase 3 end-to-end smoke test on the LOCAL stack: the Director panel.

A scene from the Harbour Lights fixture is written straight into the local database (the
build is Phase 2's smoke test), then everything else goes through the real API and the real
functions: the scene view and timeline, a person's shot length, a script edit, the director
board, director turns streamed from `director_chat` (an edit, a question, a role that may only
comment, a standing rule into production memory), approval locking the scene, and a re-split
through `script_split`.

Needs the API on :8000 and the functions running (scripts/start-functions.ps1: script_split
:8203, director_chat :8206), the Phase 3 migrations applied, and a local admin.

    python scripts/smoke_phase3.py you@hirutv.lk <admin password>
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any

import httpx
from _common import ROOT, Rest, load_env

load_env()
import os  # noqa: E402

from contracts import sceneplan  # noqa: E402
from contracts.screenplay import parse_document  # noqa: E402
from contracts.shotplan import ProposedShot, fit  # noqa: E402

SUPABASE = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321")
API = os.environ.get("API__PUBLIC_URL", "http://localhost:8000")
ANON = os.environ["SUPABASE__ANON_KEY"]
SCRIPT = ROOT / "tests" / "fixtures" / "corpus" / "harbour-lights-ep01-script.fountain"


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'' if ok else f'  -> {detail}'}")
    if not ok:
        sys.exit(1)


def sign_in(email: str, password: str) -> dict[str, str]:
    r = httpx.post(f"{SUPABASE}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def local_user(email: str, password: str, production_id: str, role: str) -> httpx.Client:
    db = Rest()
    db.insert("invitations", {"email": email, "production_id": production_id, "production_role": role})
    r = db.c.post(f"{SUPABASE}/auth/v1/admin/users", headers=db.h,
                  json={"email": email, "password": password, "email_confirm": True})
    r.raise_for_status()
    return httpx.Client(base_url=API, headers=sign_in(email, password), timeout=120)


def seed(db: Rest, pid: str) -> dict[str, Any]:
    """Episode 1, scene 1 of the fixture: one shot per script block, fitted by the kernel."""
    kamala, nimal = str(uuid.uuid4()), str(uuid.uuid4())
    db.insert("canon_entities", [
        {"id": kamala, "production_id": pid, "kind": "character", "code": "C01", "name": "Kamala",
         "aliases": ["Amma"], "core": True},
        {"id": nimal, "production_id": pid, "kind": "character", "code": "C02", "name": "Nimal", "aliases": [],
         "core": True}])
    episode = str(uuid.uuid4())
    db.insert("episodes", {"id": episode, "production_id": pid, "number": 1, "title": "The Return", "status": "ready"})
    parsed = parse_document(SCRIPT.read_text(encoding="utf-8")).scenes[0]
    scene = {"id": str(uuid.uuid4()), "production_id": pid, "episode_id": episode, "number": 1,
             "heading": parsed.heading.raw, "envelope_s": 60, "status": "split"}
    blocks, lines = [], []
    for b in parsed.blocks:
        if b.kind == "dialogue":
            line = {"id": str(uuid.uuid4()), "production_id": pid, "scene_id": scene["id"], "ord": len(lines),
                    "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                    "character_id": {"NIMAL": nimal, "KAMALA": kamala}.get(b.speaker)}
            lines.append(line)
            blocks.append({"kind": "dialogue", "text": "", "line_id": line["id"]})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    items = sceneplan.items_for(blocks, lines)
    proposal = [ProposedShot(i, i + 1, "MS") for i in range(len(items))]
    result = fit(items, proposal, envelope_s=60)
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal], result, lines)
    db.insert("scenes", {**scene, "script": blocks, "fit_report": sceneplan.fit_report(result, "rules")})
    db.insert("shots", shots)
    db.insert("dialogue_lines", line_rows)
    return {"scene": scene["id"], "shots": [s["id"] for s in shots], "kamala": kamala}


def turn(client: httpx.Client, url: str, message: str) -> list[tuple[str, dict[str, Any]]]:
    frames: list[tuple[str, dict[str, Any]]] = []
    with client.stream("POST", url, json={"message": message}, timeout=300) as r:
        check(f"turn accepted: {message!r}", r.status_code == 200, r.status_code)
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                head = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
                if "event" in head:
                    frames.append((head["event"], json.loads(head["data"])))
    return frames


def main(admin_email: str, admin_password: str) -> None:
    started = time.monotonic()
    admin = httpx.Client(base_url=API, headers=sign_in(admin_email, admin_password), timeout=120)
    pid = admin.post("/v1/productions", json={"title": f"Phase 3 smoke {uuid.uuid4().hex[:6]}",
                                              "orientation": "horizontal"}).json()["id"]
    tag = uuid.uuid4().hex[:6]
    director = local_user(f"director-{tag}@hirutv.lk", "local-director-123", pid, "director")
    writer = local_user(f"writer-{tag}@hirutv.lk", "local-writer-123", pid, "writer")
    reviewer = local_user(f"reviewer-{tag}@hirutv.lk", "local-reviewer-123", pid, "reviewer")
    db = Rest()
    s = seed(db, pid)
    base = f"/v1/productions/{pid}"
    scene_url = f"{base}/scenes/{s['scene']}"

    # ── the scene view ───────────────────────────────────────────────────────────────────
    v = reviewer.get(scene_url).json()
    check("scene view: four shots on the ladder", [x["duration_s"] for x in v["shots"]] == [6, 4, 4, 4], v.get("shots"))
    check("timeline: 18 s inside a 60 s envelope", v["timeline"]["total_s"] == 18 and not v["timeline"]["issues"],
          v["timeline"])
    check("lines are timed and bound to their shots",
          all(ln["shot_id"] and ln["start_s"] is not None for ln in v["lines"]), v["lines"])
    other = admin.post("/v1/productions", json={"title": "other", "orientation": "vertical"}).json()["id"]
    check("another production's scene is 404",
          admin.get(f"/v1/productions/{other}/scenes/{s['scene']}").status_code == 404)

    # ── a person's length ────────────────────────────────────────────────────────────────
    r = writer.patch(f"{base}/shots/{s['shots'][1]}", json={"duration_s": 8})
    check("a writer cannot set shot lengths (403)", r.status_code == 403, r.text)
    v = director.patch(f"{base}/shots/{s['shots'][1]}", json={"duration_s": 8}).json()
    check("director sets S02 to 8 s; it is locked and the scene re-timed",
          v["shots"][1]["duration_s"] == 8 and v["shots"][1]["duration_locked"]
          and [x["start_s"] for x in v["shots"]] == [0, 6, 14, 18], v["shots"])
    stored = db.get("shots", scene_id=f"eq.{s['scene']}", select="id,number,version", order="number")
    check("shot ids kept, S02 is a new version", [x["id"] for x in stored] == s["shots"]
          and stored[1]["version"] == 2 and stored[0]["version"] == 1, stored)

    # ── the script ───────────────────────────────────────────────────────────────────────
    blocks = []
    for b in v["script"]:
        if b["kind"] == "dialogue":
            ln = next(x for x in v["lines"] if x["id"] == b["line_id"])
            blocks.append({"kind": "dialogue", "speaker": ln["speaker"], "delivery": ln["delivery"],
                           "text": ln["text"], "line_id": ln["id"]})
        else:
            blocks.append({"kind": b["kind"], "text": b["text"]})
    blocks[-1]["text"] = blocks[-1]["text"].rstrip(".") + ", පුතේ."
    r = writer.put(f"{scene_url}/script", json={"blocks": blocks, "script_version": v["script_version"]})
    check("a writer edits Kamala's line", r.status_code == 200, r.text)
    v = r.json()
    check("script version 2, shots kept, line still bound to S04",
          v["script_version"] == 2 and [x["id"] for x in v["shots"]] == s["shots"]
          and v["lines"][-1]["shot_id"] == s["shots"][3] and v["lines"][-1]["text"].endswith("පුතේ."), v["lines"])
    r = writer.put(f"{scene_url}/script", json={"blocks": blocks, "script_version": 1})
    check("a stale script edit is refused (409)", r.status_code == 409, r.text)

    # ── the board ────────────────────────────────────────────────────────────────────────
    personas = {p["name"]: p["id"] for p in reviewer.get("/v1/director-personas").json()}
    check("five personas in the library", len(personas) == 5, personas)
    board = reviewer.get(f"{base}/director-board").json()
    check("default board: Classic Teledrama leads", board["is_default"]
          and board["members"][0]["persona"]["name"] == "Classic Teledrama", board)
    r = director.put(f"{base}/director-board", json={"seats": [
        {"persona_id": personas["Grounded Realist"], "seat": "lead"},
        {"persona_id": personas["Lyrical Eye"], "seat": "advisor"}]})
    check("director sets a lead and an advisor", r.status_code == 200 and not r.json()["is_default"], r.text)

    # ── director turns ───────────────────────────────────────────────────────────────────
    frames = turn(director, f"{scene_url}/chat", "make shot 3 six seconds")
    names = [e for e, _ in frames]
    check("turn streams accepted → status → plan → message → done",
          names[0] == "accepted" and "plan" in names and names[-1] == "done" and "error" not in names, names)
    done = frames[-1][1]
    message = next(d for e, d in frames if e == "message")
    check("the director answers as the board's lead", message["speaker"] == "Grounded Realist", message["speaker"])
    stored = db.get("shots", scene_id=f"eq.{s['scene']}", select="id,number,duration_s,duration_locked",
                    order="number")
    check("S03 is 6 s in the database, ids kept", stored[2]["duration_s"] == 6 and stored[2]["duration_locked"]
          and [x["id"] for x in stored] == s["shots"], stored)
    audit = db.get("audit_log", entity_id=f"eq.{s['scene']}", action="eq.scene.director_edit", select="actor_agent")
    check("the agent's change is in the audit log", audit and audit[0]["actor_agent"] == "director_chat", audit)
    check("lane reported", done.get("lane") == "edit", done)

    frames = turn(reviewer, f"{scene_url}/chat", "make shot 1 eight seconds")
    check("a reviewer is answered but nothing changes",
          "plan" not in [e for e, _ in frames]
          and db.get("shots", id=f"eq.{s['shots'][0]}", select="duration_s")[0]["duration_s"] == 6, frames[-2:])

    frames = turn(director, f"{scene_url}/chat", "How long does this scene run now?")
    reply = next(d for e, d in frames if e == "message")["blocks"][0]["text"]
    check("a question is answered without changing the plan", "plan" not in [e for e, _ in frames] and reply, reply)

    turn(director, f"{scene_url}/chat", "Remember: Kamala never cries on screen.")
    memory = director.get(f"{base}/memory").json()
    check("a standing rule is kept as production memory", any("never cries" in m["text"] for m in memory), memory)
    chunks = db.get("chunks", production_id=f"eq.{pid}", corpus="eq.memory", select="source,content")
    check("memory is indexed for search", any("never cries" in c["content"] for c in chunks), chunks)
    thread = director.get(f"{scene_url}/threads").json()[0]
    msgs = director.get(f"{base}/threads/{thread['id']}/messages").json()
    check("the thread holds every message, shared by everyone", len(msgs) == 8, [m["kind"] for m in msgs])

    # ── approval and re-split ────────────────────────────────────────────────────────────
    v = director.post(f"{scene_url}/approve").json()
    check("director approves the scene", v["status"] == "approved", v["status"])
    frames = turn(director, f"{scene_url}/chat", "make shot 4 eight seconds")
    check("an approved scene is not changed by chat", "plan" not in [e for e, _ in frames])
    check("nor by hand (409)", director.patch(f"{base}/shots/{s['shots'][3]}",
                                              json={"duration_s": 8}).status_code == 409)
    director.post(f"{scene_url}/unapprove")
    r = director.post(f"{scene_url}/resplit")
    check("re-split starts", r.status_code == 202, r.text)
    job_id = r.json()["job_id"]
    deadline = time.time() + 600
    job: dict[str, Any] = {}
    while time.time() < deadline:
        job = director.get(f"/v1/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(1.5)
    check("re-split finishes", job.get("status") == "done", job)
    v = reviewer.get(scene_url).json()
    check("the scene has a fresh shot list from script_split",
          v["shots"] and v["planner"] in ("rules", "model") and all(ln["shot_id"] for ln in v["lines"]), v["planner"])
    print(f"\nPhase 3 smoke passed in {time.monotonic() - started:.0f} s.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python scripts/smoke_phase3.py <admin email> <admin password>")
    main(sys.argv[1], sys.argv[2])
