"""Phase 2 end-to-end smoke test on the LOCAL stack: documents → build (canon → structure →
shots), a question answered by a person, canon versions and locks.

Needs the same setup as smoke_phase1.py, plus the Phase 2 functions running
(scripts/start-functions.ps1: script_split :8203, structure_build :8204, canon_extract :8205),
`API__INTERNAL_SECRET` set for both the API and the functions, and `SUPABASE__DB_URL` pointing
at the local database so the build can wait for answers.

    python scripts/smoke_phase2.py you@hirutv.lk <admin password>
"""
from __future__ import annotations

import sys
import time
import uuid
from typing import Any

import httpx
from _common import ROOT, Rest, load_env

load_env()
import os  # noqa: E402

SUPABASE = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321")
API = os.environ.get("API__PUBLIC_URL", "http://localhost:8000")
ANON = os.environ["SUPABASE__ANON_KEY"]
CORPUS = ROOT / "tests" / "fixtures" / "corpus"
# A second script that says neither its episode nor a known place: the build must ask.
UNTITLED = ("INT. KAMALA'S HOUSE - KITCHEN - NIGHT\n\nKamala counts coins on the table.\n\nKAMALA\nමේ ඇති.\n\n"
            "EXT. KALUGALA BEACH - DAY\n\nSunil drags the boat up the sand alone.\n\nSUNIL\nමට උදව් කරන්න.\n")


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
    return httpx.Client(base_url=API, headers=sign_in(email, password), timeout=60)


def wait_for(client: httpx.Client, url: str, done: Any, seconds: int = 300) -> Any:
    deadline = time.time() + seconds
    body: Any = None
    while time.time() < deadline:
        body = client.get(url).json()
        if done(body):
            return body
        time.sleep(1.5)
    check(f"waited for {url}", False, body)


def main(admin_email: str, admin_password: str) -> None:
    admin = httpx.Client(base_url=API, headers=sign_in(admin_email, admin_password), timeout=60)
    pid = admin.post("/v1/productions", json={"title": f"Phase 2 smoke {uuid.uuid4().hex[:6]}",
                                              "orientation": "horizontal"}).json()["id"]
    tag = uuid.uuid4().hex[:6]
    producer = local_user(f"producer-{tag}@hirutv.lk", "local-producer-123", pid, "producer")
    writer = local_user(f"writer-{tag}@hirutv.lk", "local-writer-123", pid, "writer")
    base = f"/v1/productions/{pid}"

    names = ["harbour-lights-canon-index.md", "harbour-lights-bible.md", "harbour-lights-outline.txt",
             "harbour-lights-ep01-script.fountain"]
    for name in names:
        r = producer.post(f"{base}/documents", files={"file": (name, (CORPUS / name).read_bytes(), "text/plain")})
        check(f"upload {name}", r.status_code == 201, r.text)
    r = producer.post(f"{base}/documents", data={"role": "script"},
                      files={"file": ("untitled-draft.fountain", UNTITLED.encode(), "text/plain")})
    check("upload an unnumbered script", r.status_code == 201, r.text)
    docs = wait_for(producer, f"{base}/documents", lambda ds: all(d["status"] == "ready" for d in ds))
    db = Rest()
    stored = db.get("documents", production_id=f"eq.{pid}", select="filename,text_path")
    check("doc_ingest keeps the extracted text for the build", all(d["text_path"] for d in stored), stored)
    check("documents ready", len(docs) == 5)

    r = writer.post(f"{base}/build")
    check("a writer cannot start a build (403)", r.status_code == 403, r.text)
    r = producer.post(f"{base}/build")
    check("producer starts the build", r.status_code == 202, r.text)
    job_id = r.json()["job_id"]
    check("a second build is refused while one runs", producer.post(f"{base}/build").status_code == 409)

    view = wait_for(writer, f"{base}/build", lambda v: v["status"] in ("waiting_input", "done", "failed"))
    check("the build stops on questions", view["status"] == "waiting_input", view)
    stages = {s["stage"]: s["state"] for s in view["stages"]}
    check("canon and reading are done, episodes in progress",
          stages["read"] == "done" and stages["canon"] == "done" and stages["episodes"] == "active", stages)
    canon = writer.get(f"{base}/canon").json()
    codes = {c["code"]: c for c in canon}
    check("canon extracted with the index codes", {"C01", "C02", "C03", "C04", "L01", "L02", "L03", "P01"} <= set(codes),
          sorted(codes))
    check("voice pin from the index", codes["C01"]["current"]["voice_pin"].startswith("low, clipped female voice"),
          codes["C01"]["current"])
    questions = writer.get(f"{base}/questions?status=open").json()
    keys = sorted(q["title"] for q in questions)
    check("it asks which episode the untitled script is and about the beach", len(questions) == 2, keys)

    for q in questions:
        if "episode" in q["title"]:
            r = writer.post(f"{base}/questions/{q['id']}/answer", json={"text": "Episode 5"})
        else:
            check("the place question suggests L02", q["options"][0]["value"] == "L02", q)
            r = writer.post(f"{base}/questions/{q['id']}/answer", json={"value": "new"})
        check(f"writer answers: {q['body'][:50]}", r.status_code == 200, r.text)
    check("the last answer resumed the build", r.json()["resumed"] is True, r.json())

    view = wait_for(writer, f"{base}/build", lambda v: v["status"] in ("done", "failed"), seconds=1500)
    check("the build finishes", view["status"] == "done", view)
    stages = {s["stage"]: s["state"] for s in view["stages"]}
    check("every stage done, review active",
          all(stages[s] == "done" for s in ("read", "canon", "episodes", "scenes", "shots", "continuity"))
          and stages["review"] == "active", stages)

    eps = writer.get(f"{base}/episodes").json()
    by_no = {e["number"]: e for e in eps}
    check("episodes 1-4 from the outline and 5 from the answered script", sorted(by_no) == [1, 2, 3, 4, 5], sorted(by_no))
    check("episode 1 has 6 scenes with shots", by_no[1]["scenes"] == 6 and by_no[1]["shots"] >= 12
          and by_no[1]["openable"], by_no[1])
    check("episode 1 title from the script", by_no[1]["title"] == "The Return", by_no[1])
    check("episode 5 has 2 scenes", by_no[5]["scenes"] == 2, by_no[5])
    lines = db.get("dialogue_lines", production_id=f"eq.{pid}", select="shot_id,character_id,text")
    check("every line is bound to a shot and a character", lines and all(ln["shot_id"] and ln["character_id"]
                                                                          for ln in lines), lines)
    shots = db.get("shots", production_id=f"eq.{pid}", select="duration_s")
    check("every shot is 4, 6 or 8 s", {s["duration_s"] for s in shots} <= {4, 6, 8})
    canon = writer.get(f"{base}/canon").json()
    beach = [c for c in canon if c["name"].lower() == "kalugala beach"]
    check("answering 'a new location' added the beach to the canon", len(beach) == 1, [c["name"] for c in canon])

    c01 = next(c for c in canon if c["code"] == "C01")
    r = writer.post(f"{base}/canon/{c01['id']}/versions", json={"card": {"voice": "x"}})
    check("a writer cannot edit canon (403)", r.status_code == 403)
    r = producer.post(f"{base}/canon/{c01['id']}/versions",
                      json={"card": {**c01["current"]["card"], "voice": "low, tired"}})
    check("producer writes canon version 2", r.status_code == 201 and r.json()["version"] == 2, r.text)
    check("lock C01", producer.post(f"{base}/canon/{c01['id']}/lock").json()["locked"] is True)

    r = producer.post(f"{base}/build")
    check("rebuild starts", r.status_code == 202, r.text)
    view = wait_for(writer, f"{base}/build", lambda v: v["job_id"] != job_id and v["status"] in ("done", "failed",
                                                                                                "waiting_input"), seconds=1500)
    check("rebuild finishes without new questions", view["status"] == "done", view)
    c01_after = writer.get(f"{base}/canon/{c01['id']}").json()
    check("the locked item kept the person's version", c01_after["current_version"] == 2
          and c01_after["current"]["card"]["voice"] == "low, tired", c01_after["current"])
    eps2 = {e["number"]: e for e in writer.get(f"{base}/episodes").json()}
    check("rebuild keeps the same episodes", [e["id"] for e in eps2.values()] == [e["id"] for e in by_no.values()]
          and eps2[1]["scenes"] == 6)
    check("the canon grew no duplicates", len(writer.get(f"{base}/canon").json()) == len(canon))

    other = admin.post("/v1/productions", json={"title": "Other", "orientation": "vertical"}).json()["id"]
    check("another production's build is 404", producer.get(f"/v1/productions/{other}/build").status_code == 404)
    usage = db.get("token_usage", production_id=f"eq.{pid}", select="phase")
    print(f"      model calls recorded: {len(usage)} ({sorted({u['phase'] for u in usage})})")
    print("phase 2 smoke test passed")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
