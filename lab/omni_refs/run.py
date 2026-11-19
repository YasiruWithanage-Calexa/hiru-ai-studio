"""Omni reference-image lab: does the person keep their sheet's face and clothes once they come into view?

    .venv/Scripts/python.exe lab/omni_refs/run.py --name shot02                    # dry: writes the requests, sends nothing
    .venv/Scripts/python.exe lab/omni_refs/run.py --name shot02 --variants B --yes # PAID: one take per variant

Each variant goes to `runs/<NNN>_<variant>/`: request.json (the exact body, image bytes replaced by file names),
prompt.txt, and after a paid run take.mp4, response.json (no video bytes), usage.json and stills/ (one frame a second).
Variants are described in build.py. The key is GOOGLE__API_KEY from the repo's .env; nothing else is read or written.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if __package__ in (None, ""):
    sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "video_render")]

import build  # noqa: E402

BASE_URL = "https://generativelanguage.googleapis.com"
RATE_720P = 0.10  # $/s, contracts/costs.py SEED_PRICES (marked "confirm"); 360p is not listed, assumed no dearer


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def _next_dir(variant: str) -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    n = 1 + max((int(p.name[:3]) for p in runs.iterdir() if p.name[:3].isdigit()), default=0)
    out = runs / f"{n:03d}_{variant}"
    out.mkdir()
    return out


def requests_for(meta: dict, variants: list[str]) -> dict[str, dict]:
    makers = {"A": lambda: build.request_a(meta), "B": lambda: build.request_b(meta, task=None),
              "C": lambda: build.request_b(meta, task="reference_to_video")}
    return {v: makers[v]() for v in variants}


def _stills(video: Path, out: Path, seconds: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    out.mkdir(exist_ok=True)
    for s in range(seconds + 1):
        t = min(s, seconds - 0.1)
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",  # noqa: S603  our own paths
                        str(out / f"t{s:02d}.png")], check=False)


def send(req: dict, folder: Path, out: Path) -> dict:
    """One paid take, through the product's own Omni module for everything after the POST."""
    import httpx
    from video_render.engine import omni
    from video_render.engine.transport import post_json

    key = _env("GOOGLE__API_KEY")
    started = time.monotonic()
    with httpx.Client() as client:
        response = post_json(client, f"{BASE_URL}/v1beta/interactions?key={key}",
                             json=build.body(req, folder, with_bytes=True), timeout=1680.0)
    outcome = omni.read_outcome(response)
    data = outcome["inline"]
    if data is None:
        omni.wait(outcome["file_name"], api_key=key, base_url=BASE_URL, interval=5.0, deadline=started + 1680)
        data = omni.download(outcome["file_name"], api_key=key, base_url=BASE_URL, attempts=5)
    (out / "take.mp4").write_bytes(data)
    slim = {k: v for k, v in response.items() if k not in ("steps", "outputs", "input")}
    (out / "response.json").write_text(json.dumps(slim, indent=1, ensure_ascii=False), encoding="utf-8")
    usage = {"interaction_id": outcome["interaction_id"], "usage": outcome["usage"],
             "tokens": omni.usage_tokens(outcome["usage"]), "seconds_waited": round(time.monotonic() - started, 1)}
    (out / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    _stills(out / "take.mp4", out / "stills", req["duration_s"])
    return usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="the input folder fetch.py wrote")
    ap.add_argument("--variants", default="A,B,C")
    ap.add_argument("--yes", action="store_true", help="send: each variant is one PAID Omni take")
    args = ap.parse_args()
    folder = HERE / "input" / args.name
    meta = build.load(folder)
    variants = [v.strip().upper() for v in args.variants.split(",") if v.strip()]
    reqs = requests_for(meta, variants)

    ceiling = len(reqs) * meta["duration_s"] * RATE_720P
    print(f"{len(reqs)} take(s) at {build.RESOLUTION}, {meta['duration_s']} s, {build.MODEL}; "
          f"ceiling ~${ceiling:.2f} at the 720p rate")
    for v, req in reqs.items():
        out = _next_dir(v)
        (out / "request.json").write_text(json.dumps(build.body(req, folder, with_bytes=False), indent=1,
                                                     ensure_ascii=False), encoding="utf-8")
        (out / "prompt.txt").write_text(req["prompt"], encoding="utf-8")
        print(f"  {v}: {len(req['images'])} image(s) {req['images']}, task={req['task']} -> {out.relative_to(ROOT)}")
        if args.yes:
            usage = send(req, folder, out)
            print(f"     done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to make the takes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
