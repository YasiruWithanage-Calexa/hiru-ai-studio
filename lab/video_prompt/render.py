"""Render one clip's NEW prompt with Omni Flash 1.2, from one model's run, so the person can hear the difference.

    .venv/Scripts/python.exe lab/video_prompt/render.py --slate 4A-2 --runs 002_gpt-6.1-terra,003_gpt-6.1-sol
    .venv/Scripts/python.exe lab/video_prompt/render.py --slate 4A-2 --runs ... --yes      PAID: one 360p take per run

The prompt is the run's assembled prompt (run.py `assemble`) WITHOUT the picture citations: the lab has no first frame
or sheets for this scene, so it is text to video. Writes runs/<run>/takes/<slate>/: prompt.txt, request.json, and after
a paid run take.mp4, usage.json, stills/. A take that exists is never made again. Key: GOOGLE__API_KEY from .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "video_render")]

import run as lab  # noqa: E402  (this lab's run.py)

MODEL = "gemini-omni-1.2-flash"
RESOLUTION = "360p"
RATE_720P = 0.10  # $/s, contracts/costs.py ("confirm"); 360p assumed no dearer
CAP_USD = 1.50
BASE_URL = "https://generativelanguage.googleapis.com"


def prompt_for(world: dict, run_dir: str, slate: str) -> tuple[str, int]:
    shot = next(s for s in world["scene"].shots if str(s.row.get("slate")) == slate)
    ans = json.loads((HERE / "runs" / run_dir / "answers" / f"{slate}.json").read_text(encoding="utf-8"))
    if ans["faults"]:
        raise SystemExit(f"{run_dir} {slate} fell back to today's prompt: nothing new to render")
    text = lab.assemble(lab.Direction.model_validate(ans["direction"]), shot, world)
    from contracts.video_gen import OMNI_CITATION_HEAD

    return text.split(OMNI_CITATION_HEAD)[0].strip(), int(shot.duration_s)


def body(prompt: str, seconds: int, aspect: str) -> dict:
    return {"model": MODEL, "input": [{"type": "text", "text": prompt}], "background": False, "store": True,
            "generation_config": {"video_config": {"task": "text_to_video"}},
            "response_format": {"type": "video", "aspect_ratio": aspect, "resolution": RESOLUTION,
                                "duration": f"{seconds}s", "delivery": "uri"}}


def stills(video: Path, out: Path, seconds: int) -> None:
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    out.mkdir(exist_ok=True)
    for s in range(0, seconds + 1):
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", str(min(s, seconds - 0.1)), "-i", str(video),  # noqa: S603
                        "-frames:v", "1", str(out / f"t{s:02d}.png")], check=False)


def send(req: dict, out: Path, seconds: int) -> dict:
    import httpx
    from video_render.engine import omni
    from video_render.engine.transport import post_json

    key = lab.env("GOOGLE__API_KEY")
    started = time.monotonic()
    with httpx.Client() as client:
        response = post_json(client, f"{BASE_URL}/v1beta/interactions?key={key}", json=req, timeout=1680.0)
    outcome = omni.read_outcome(response)
    data = outcome["inline"]
    if data is None:
        omni.wait(outcome["file_name"], api_key=key, base_url=BASE_URL, interval=5.0, deadline=started + 1680)
        data = omni.download(outcome["file_name"], api_key=key, base_url=BASE_URL, attempts=5)
    (out / "take.mp4").write_bytes(data)
    usage = {"interaction_id": outcome["interaction_id"], "usage": outcome["usage"],
             "tokens": omni.usage_tokens(outcome["usage"]), "seconds_waited": round(time.monotonic() - started, 1)}
    (out / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    stills(out / "take.mp4", out / "stills", seconds)
    return usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slate", required=True)
    ap.add_argument("--runs", required=True, help="run folders, comma separated")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    world = lab.load()
    aspect = "16:9" if world["prod"].aspect_ratio in ("16:9", "") else world["prod"].aspect_ratio
    todo = []
    for run_dir in [r.strip() for r in args.runs.split(",") if r.strip()]:
        prompt, seconds = prompt_for(world, run_dir, args.slate)
        out = HERE / "runs" / run_dir / "takes" / args.slate
        out.mkdir(parents=True, exist_ok=True)
        req = body(prompt, seconds, aspect)
        (out / "prompt.txt").write_text(prompt, encoding="utf-8")
        (out / "request.json").write_text(json.dumps(req, indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{run_dir} {args.slate}: {seconds} s {aspect} {RESOLUTION}{'  [have take, skipped]' if have else ''}")
        if not have:
            todo.append((req, out, seconds))
    cost = sum(s for _, _, s in todo) * RATE_720P
    print(f"{len(todo)} take(s), ceiling ~${cost:.2f} at the 720p rate (cap ${CAP_USD:.2f})")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to make the takes.")
        return 0
    if cost > CAP_USD:
        print("refused: past the cap")
        return 1
    for req, out, seconds in todo:
        usage = send(req, out, seconds)
        print(f"  {out.relative_to(HERE)} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
