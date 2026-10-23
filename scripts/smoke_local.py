"""End-to-end smoke test against the LOCAL stack: Supabase Auth → API → function → job events.

Prerequisites (see README "Local development"):
    npx supabase start
    python scripts/create_admin.py you@hirutv.lk --password <pw>
    uvicorn api.main:app --port 8000          (from src/, with .env loaded)
    powershell -File scripts/start-functions.ps1

    python scripts/smoke_local.py you@hirutv.lk <pw>
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx
import jwt

SUPABASE = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321")
API = os.environ.get("API__PUBLIC_URL", "http://localhost:8000")


def _env_file(name: str) -> str:
    for line in open(".env", encoding="utf-8"):
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'' if ok else f'  -> {detail}'}")
    if not ok:
        sys.exit(1)


def main(email: str, password: str) -> None:
    anon = os.environ.get("SUPABASE__ANON_KEY") or _env_file("SUPABASE__ANON_KEY")
    r = httpx.post(f"{SUPABASE}/auth/v1/token?grant_type=password",
                   headers={"apikey": anon}, json={"email": email, "password": password})
    check("sign in through Supabase Auth", r.status_code == 200, r.text)
    token = r.json()["access_token"]
    print(f"      token alg = {jwt.get_unverified_header(token)['alg']}")
    h = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=API, headers=h, timeout=15) as api:
        me = api.get("/v1/me")
        check("GET /v1/me as admin", me.status_code == 200 and me.json()["app_role"] == "admin", me.text)

        created = api.post("/v1/productions", json={"title": f"Smoke {uuid.uuid4().hex[:6]}",
                                                    "orientation": "horizontal"})
        check("POST /v1/productions", created.status_code == 201, created.text)
        pid = created.json()["id"]
        listed = api.get("/v1/productions").json()
        check("production is listed", any(p["id"] == pid for p in listed))

        # Same production read directly through PostgREST with the user's token: RLS lets an admin see it.
        rls = httpx.get(f"{SUPABASE}/rest/v1/productions", params={"id": f"eq.{pid}"},
                        headers={**h, "apikey": anon})
        check("RLS: admin reads it through Supabase directly", len(rls.json()) == 1, rls.text)
        write = httpx.patch(f"{SUPABASE}/rest/v1/productions", params={"id": f"eq.{pid}"},
                            headers={**h, "apikey": anon, "Prefer": "return=representation"},
                            json={"title": "changed from the browser"})
        check("RLS: browser cannot write directly", write.json() == [], write.text)

        invitee = f"smoke-{uuid.uuid4().hex[:6]}@hirutv.lk"
        inv = api.post("/v1/invitations", json={"email": invitee, "production_id": pid,
                                                "production_role": "writer"})
        check("POST /v1/invitations sends an invite", inv.status_code == 201
              and inv.json()["outcome"] == "invited", inv.text)

        started = api.post("/v1/jobs/echo", json={"message": "hello hiru"})
        check("POST /v1/jobs/echo", started.status_code == 202, started.text)
        job_id = started.json()["job_id"]
        job: dict = {}
        for _ in range(40):
            job = api.get(f"/v1/jobs/{job_id}").json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(0.25)
        check("echo job finished via the local function", job.get("status") == "done", job)
        check("job result", job["result"]["echo"] == "hello hiru", job)
        events = api.get(f"/v1/jobs/{job_id}/events").json()
        check("job events recorded", [e["type"] for e in events] == ["status", "progress", "status"], events)
    print("smoke test passed")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
