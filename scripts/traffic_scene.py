"""Measure what one shot page costs (plan/2026-11-08c phase 0). Run it before and after each phase.

    # the API must run with DEBUG_TRAFFIC=true (it then serves GET /debug/traffic and logs each minute)
    python scripts/traffic_scene.py --production <id> --episode <id> --scene <id> --shot <id> --token <jwt>
    python scripts/traffic_scene.py ... --email me@x.lk --password ...      # signs in with SUPABASE__ANON_KEY instead
    python scripts/traffic_scene.py ... --idle 300 --out plan/2026-11-08c/after-phase-1.json

Steps, each counted on its own (API calls, Supabase queries, bytes sent, /files served from disk vs from Supabase):
  1 open      the reads the shot page makes (`/page`, usage, me), then every picture it links, once
  2 reopen    the same page again: pictures must come from the disk copy, not Supabase
  3 camera    one camera edit (a no-op write: the field is set to what the shot already has)
  4 idle      nothing happens for --idle seconds (default 60): the interface would make 0 requests here, so this
              step checks the API side is quiet
  5 job       ONLY with --with-job: starts one frame job and waits for it. THIS CALLS THE IMAGE MODEL AND COSTS MONEY.
              There is no fake image provider for frames; never use it without the person's yes.

Writes the numbers to --out (default plan/2026-11-08c/baseline.json). Reads only; step 3 writes the shot's camera back
to what it was.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common

_common.load_env()

import httpx  # noqa: E402


def sign_in(email: str, password: str) -> str:
    url = os.environ.get("SUPABASE__URL", "http://127.0.0.1:54321").rstrip("/")
    r = httpx.post(f"{url}/auth/v1/token", params={"grant_type": "password"},
                   headers={"apikey": os.environ["SUPABASE__ANON_KEY"]}, json={"email": email, "password": password})
    r.raise_for_status()
    return str(r.json()["access_token"])


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    routes: dict[str, dict[str, int]] = {}
    for name, now in after["routes"].items():
        was = before["routes"].get(name, {"calls": 0, "db": 0, "bytes": 0})
        diff = {k: now[k] - was[k] for k in ("calls", "db", "bytes")}
        if diff["calls"]:
            routes[name] = diff
    files = {k: after["files"][k] - before["files"][k] for k in after["files"]}
    return {"api_calls": sum(r["calls"] for r in routes.values()), "db_queries": sum(r["db"] for r in routes.values()),
            "bytes": sum(r["bytes"] for r in routes.values()), "files": files, "routes": routes}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=os.environ.get("API__PUBLIC_URL", "http://localhost:8000"))
    for name in ("production", "episode", "scene", "shot"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--token", default=os.environ.get("HIRU_TOKEN", ""))
    ap.add_argument("--email")
    ap.add_argument("--password")
    ap.add_argument("--idle", type=int, default=60)
    ap.add_argument("--with-job", action="store_true", help="also start one frame job (CALLS THE IMAGE MODEL)")
    ap.add_argument("--out", default="plan/2026-11-08c/baseline.json")
    a = ap.parse_args()

    token = a.token or (sign_in(a.email, a.password) if a.email and a.password else "")
    if not token:
        print("Give --token (or HIRU_TOKEN), or --email and --password.", file=sys.stderr)
        return 2
    c = httpx.Client(base_url=a.api.rstrip("/"), headers={"Authorization": f"Bearer {token}"}, timeout=60.0)
    base = f"/v1/productions/{a.production}"

    def snap() -> dict[str, Any]:
        r = c.get("/debug/traffic")
        if r.status_code != 200:
            raise SystemExit("GET /debug/traffic failed: start the API with DEBUG_TRAFFIC=true (local only).")
        return r.json()

    def step(name: str, fn: Any) -> dict[str, Any]:
        before = snap()
        extra = fn() or {}
        out = {**delta(before, snap()), **extra}
        print(f"{name:8} api={out['api_calls']:>3} db={out['db_queries']:>3} bytes={out['bytes']:>10,} "
              f"files={out['files']}")
        return out

    def urls_in(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and (k.endswith("url") or k.endswith("_url")) and "/files/" in v:
                    found.add(v)
                else:
                    found |= urls_in(v)
        elif isinstance(node, list):
            for v in node:
                found |= urls_in(v)
        return found

    def open_page() -> dict[str, Any]:
        page = c.get(f"{base}/scenes/{a.scene}/page")
        if page.status_code == 404:  # an API without phase 4: the five reads it replaces
            body: dict[str, Any] = {"view": c.get(f"{base}/scenes/{a.scene}").json(),
                                    "production": c.get(f"{base}/scenes/{a.scene}/production").json()}
            c.get(f"{base}/episodes/{a.episode}")
            c.get(f"{base}/scenes/{a.scene}/threads")
        else:
            page.raise_for_status()
            body = page.json()
        c.get("/v1/usage")
        c.get("/v1/me")
        links = urls_in(body)
        for link in sorted(links):  # a browser fetches each distinct URL once
            c.get(link.replace(a.api.rstrip("/"), "") if link.startswith(a.api) else link)
        return {"pictures": len(links)}

    result: dict[str, Any] = {"api": a.api, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": {}}
    result["steps"]["open"] = step("open", open_page)
    result["steps"]["reopen"] = step("reopen", open_page)

    def camera() -> None:
        shot = c.get(f"{base}/shots/{a.shot}").json()
        current = shot["camera"]["current"]
        c.patch(f"{base}/shots/{a.shot}/camera", json={"framing": current["framing"]}).raise_for_status()

    result["steps"]["camera"] = step("camera", camera)
    result["steps"]["idle"] = step("idle", lambda: time.sleep(a.idle))

    if a.with_job:
        def job() -> dict[str, Any]:
            started = c.post(f"{base}/shots/{a.shot}/frames", json={"count": 1, "stage": "draft"})
            started.raise_for_status()
            job_id = started.json()["job_id"]
            for _ in range(200):
                status = c.get(f"/v1/jobs/{job_id}").json()["status"]
                if status in ("done", "failed", "cancelled"):
                    return {"job_status": status}
                time.sleep(3)
            return {"job_status": "timeout"}

        result["steps"]["job"] = step("job", job)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
