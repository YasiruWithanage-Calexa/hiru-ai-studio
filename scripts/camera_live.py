"""The paid end-to-end test of the camera fixes (the audit of 2026-11-21: plan/2026-11-20c + 20d as the labs proved
them), on ONE real scene, through the product's own API and functions: the person's clicks, in order.

PAID and it WRITES to the hosted database (the person's yes of 2026-11-21: SCENE 03 of Love Hour 4, cap $3). It needs
the API on 127.0.0.1:8001 and the functions (Raphael, shot producer + frame render on graph, video render) running.

    python scripts/camera_live.py backup          (free) the scene's shots, frames, prompts, takes -> the run folder
    python scripts/camera_live.py plan --yes      "Plan with Raphael" (Raphael, then the Camera agent)
    python scripts/camera_live.py look            (free) the camera of every shot: moment, power, move, angle
    python scripts/camera_live.py frames --yes    "Draw first frames" for the scene (shot prompts, then frames, medium)
    python scripts/camera_live.py accept --yes    accept each shot's newest finished frame (free, writes)
    python scripts/camera_live.py prompts --yes   "Generate video prompts" (from the stored shot prompts)
    python scripts/camera_live.py takes --yes --shots 3A-1,3C-1   one 360p Omni Flash draft take per shot
    python scripts/camera_live.py report          (free) frames, prompts and takes downloaded + report.md

Spend: the run's `token_usage` rows at the product's list prices (`contracts.costs.actual_total`), and each take at the
720p ceiling ($0.10/s), as the labs counted it. A paid step is refused when its worst case would pass CAP_USD.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from contracts.costs import LIST_PRICES, actual_total  # noqa: E402
from hiru_ai.adapters import supabase_rest  # noqa: E402
from hiru_ai.core.settings import get_settings  # noqa: E402

PID = "b89f79a3-3ce6-4123-aee5-759f35c09d69"  # Love Hour 4
SCENE = "bd5a6483-0eef-4a66-afac-b60556478618"  # SCENE 03, THE UNEXPECTED ENCOUNTER
API = "http://127.0.0.1:8001"
CAP_USD = 3.00
TAKE_USD_PER_S = 0.10  # the 720p ceiling, as lab/camera_moves' wallet
WORST = {"plan": 0.90, "frames": 1.20, "prompts": 0.10}
RUNS = ROOT / "lab" / "camera_moves" / "runs" / "live"


def rest() -> Any:
    s = get_settings()
    return supabase_rest.Rest(s.supabase.url, s.supabase.service_role_key.get_secret_value())


def now() -> str:
    return datetime.now(UTC).isoformat()


class Run:
    def __init__(self) -> None:
        RUNS.mkdir(parents=True, exist_ok=True)
        self.file = RUNS / "state.json"
        self.state: dict[str, Any] = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {
            "started": now(), "jobs": [], "renders": []}
        self.rest = rest()
        self.http = httpx.Client(base_url=f"{API}/v1/productions/{PID}", timeout=120)

    def save(self) -> None:
        self.file.write_text(json.dumps(self.state, indent=1, ensure_ascii=False, default=str), encoding="utf-8")

    def shots(self) -> list[dict[str, Any]]:
        return self.rest.select("shots", {"scene_id": f"eq.{SCENE}", "select": "*", "order": "number"})

    def spent(self) -> float:
        rows = self.rest.select("token_usage", {"production_id": f"eq.{PID}",
                                                "created_at": f"gte.{self.state['started']}", "select": "*"})
        tokens = actual_total(rows, LIST_PRICES).micros / 1e6
        takes = sum(float(r.get("seconds") or 0) * TAKE_USD_PER_S for r in self.state["renders"])
        return round(tokens + takes, 4)

    def allow(self, worst: float, what: str) -> None:
        spent = self.spent()
        print(f"spent so far ${spent:.4f}; {what} at worst ${worst:.2f}; cap ${CAP_USD:.2f}")
        if spent + worst > CAP_USD:
            raise SystemExit("REFUSED: it would pass the cap")

    def wait(self, job_id: str, what: str, limit_s: int = 1500) -> dict[str, Any]:
        started = time.time()
        last = ""
        while True:
            job = httpx.get(f"{API}/v1/jobs/{job_id}", timeout=30).json()
            events = httpx.get(f"{API}/v1/jobs/{job_id}/events", timeout=30).json()
            for e in events[len(last.split("\n")) - 1 if last else 0:]:
                text = (e.get("payload") or {}).get("text") or ""
                if text:
                    print(f"  [{e.get('type')}] {text[:220]}", flush=True)
            last = "\n" * (len(events) + 1)
            if job["status"] in ("done", "failed", "cancelled"):
                secs = round(time.time() - started)
                print(f"{what}: {job['status']} in {secs} s {job.get('error') or ''}")
                self.state["jobs"].append({"what": what, "job_id": job_id, "status": job["status"], "seconds": secs,
                                           "result": job.get("result"), "error": job.get("error"), "at": now()})
                self.save()
                return job
            if time.time() - started > limit_s:
                raise SystemExit(f"{what}: still {job['status']} after {limit_s} s")
            time.sleep(5)

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        r = self.http.post(path, json=body or {})
        if r.status_code >= 400:
            raise SystemExit(f"POST {path}: {r.status_code} {r.text[:400]}")
        return r.json()


def backup(run: Run) -> None:
    out = {"shots": run.shots(),
           "frames": run.rest.select("first_frames", {"shot_id": f"in.({','.join(s['id'] for s in run.shots())})",
                                                      "select": "*"}),
           "prompts": run.rest.select("video_prompts", {"shot_id": f"in.({','.join(s['id'] for s in run.shots())})",
                                                        "select": "*"}),
           "scene": run.rest.first("scenes", {"id": f"eq.{SCENE}", "select": "*"})}
    (RUNS / "before.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"backup: {len(out['shots'])} shots, {len(out['frames'])} frames, {len(out['prompts'])} prompts")


def look(run: Run) -> None:
    rows = []
    for s in run.shots():
        d = s.get("design") or {}
        c = d.get("camera") or {}
        rec = d.get("recommended") or {}
        rows.append({"slate": s.get("slate"), "size": s.get("framing"), "take": s.get("duration_s"),
                     "state": c.get("state"), "moment": c.get("moment"), "intensity": c.get("intensity"),
                     "power": c.get("power"), "move": rec.get("movement"), "speed": rec.get("speed"),
                     "angle": rec.get("angle"), "height": rec.get("height"), "angle_reason": c.get("angle_reason"),
                     "sentence": c.get("camera_sentence"), "why": c.get("why"), "faults": c.get("faults"),
                     "peak": c.get("peak_slate"), "arc": c.get("arc"), "language": c.get("language")})
    (RUNS / "camera.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    if rows:
        print(f"language: {rows[0]['language']}\narc: {rows[0]['arc']}\npeak: {rows[0]['peak']}")
    for r in rows:
        print(f"{r['slate']:6} {r['size']:6} {r['take']}s | {r['moment']} {r['intensity']} power {r['power']} | "
              f"{r['move']} ({r['speed']}) | {r['angle']} / {r['height']} | {r['state']}")
        print(f"        \"{r['sentence']}\"")
        if r["angle_reason"]:
            print(f"        angle: {r['angle_reason']}")
        if r["faults"]:
            print(f"        FAULTS: {r['faults']}")


def accept(run: Run) -> None:
    for s in run.shots():
        frames = run.rest.select("first_frames", {"shot_id": f"eq.{s['id']}", "status": "eq.done", "stage": "neq.draft",
                                                  "created_at": f"gte.{run.state['started']}",
                                                  "select": "id,created_at",
                                                  "order": "created_at.desc", "limit": "1"})
        if frames:
            run.post(f"/frames/{frames[0]['id']}/accept")
            print(f"{s['slate']}: accepted {frames[0]['id']}")
        else:
            print(f"{s['slate']}: no new frame")


def takes(run: Run, slates: list[str]) -> None:
    by = {s["slate"]: s for s in run.shots()}
    for slate in slates:
        s = by[slate]
        run.allow(float(s["duration_s"]) * TAKE_USD_PER_S, f"take {slate}")
        started = run.post(f"/shots/{s['id']}/renders", {"draft": True})
        run.state["renders"].append({"slate": slate, "seconds": s["duration_s"], **started})
        run.save()
        run.wait(str(started["job_id"]), f"take {slate}", limit_s=600)


def report(run: Run) -> None:
    from hiru_ai.adapters.storage import SupabaseFiles

    files = SupabaseFiles(run.rest)
    out = RUNS / "files"
    out.mkdir(exist_ok=True)
    md = ["# Camera fixes, paid run: Love Hour 4, SCENE 03", "", f"Spent ${run.spent():.4f} of ${CAP_USD:.2f}.", ""]
    for s in run.shots():
        slate = s["slate"]
        sp = (s.get("design") or {}).get("shot_prompt") or {}
        md += [f"## {slate} ({s['framing']}, {s['duration_s']} s)", ""]
        fr = run.rest.select("first_frames", {"shot_id": f"eq.{s['id']}", "accepted_at": "not.is.null",
                                              "stage": "neq.draft", "select": "*", "limit": "1"})
        if fr and fr[0].get("storage_path"):
            (out / f"{slate}_frame.png").write_bytes(files.download("frames", fr[0]["storage_path"]))
            (out / f"{slate}_frame_prompt.txt").write_text(fr[0].get("prompt") or "", encoding="utf-8")
            md.append(f"Frame: files/{slate}_frame.png (painted {fr[0]['created_at'][:19]})")
        vp = run.rest.select("video_prompts", {"shot_id": f"eq.{s['id']}", "select": "*", "order": "version.desc",
                                               "limit": "1"})
        if vp:
            (out / f"{slate}_video_prompt.txt").write_text(vp[0].get("prose") or "", encoding="utf-8")
            md.append(f"Video prompt v{vp[0]['version']}: files/{slate}_video_prompt.txt")
        tk = run.rest.select("takes", {"shot_id": f"eq.{s['id']}", "created_at": f"gte.{run.state['started']}",
                                       "select": "*", "order": "created_at.desc", "limit": "1"})
        if tk and tk[0].get("storage_path"):
            (out / f"{slate}_take.mp4").write_bytes(files.download("takes", tk[0]["storage_path"]))
            md.append(f"Take: files/{slate}_take.mp4")
        if sp.get("frame"):
            md.append(f"Shot prompt frame: {sp['frame'].get('composition', '')}")
        md.append("")
    (RUNS / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(f"report: {RUNS / 'report.md'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["backup", "plan", "look", "frames", "accept", "prompts", "takes", "report",
                                     "spend"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    run = Run()
    if a.step in ("plan", "frames", "accept", "prompts", "takes") and not a.yes:
        raise SystemExit("This step writes (and pays): --yes only after the person said yes.")
    if a.step == "backup":
        backup(run)
    elif a.step == "plan":
        run.allow(WORST["plan"], "Raphael + Camera agent")
        job = run.post(f"/scenes/{SCENE}/raphael/plan", {})
        run.wait(str(job["job_id"]), "plan with Raphael")
        print(f"spent ${run.spent():.4f}")
    elif a.step == "look":
        look(run)
    elif a.step == "frames":
        run.allow(WORST["frames"], "shot prompts + medium frames")
        job = run.post(f"/scenes/{SCENE}/frames", {"quality": "medium", "only_missing": False})
        run.wait(str(job["job_id"]), "draw first frames")
        print(f"spent ${run.spent():.4f}")
    elif a.step == "accept":
        accept(run)
    elif a.step == "prompts":
        run.allow(WORST["prompts"], "video prompts")
        job = run.post(f"/scenes/{SCENE}/prompts")
        run.wait(str(job["job_id"]), "generate video prompts")
        print(f"spent ${run.spent():.4f}")
    elif a.step == "takes":
        takes(run, [x for x in a.shots.split(",") if x])
        print(f"spent ${run.spent():.4f}")
    elif a.step == "report":
        report(run)
    else:
        print(f"spent ${run.spent():.4f}")


if __name__ == "__main__":
    main()
