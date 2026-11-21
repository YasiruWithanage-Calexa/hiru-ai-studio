"""Render the Camera agent's camera in Omni Flash 1.2, changing NOTHING else in the prompt.

    .venv/Scripts/python.exe lab/camera_agent/render.py           dry: writes prompts + requests, sends nothing
    .venv/Scripts/python.exe lab/camera_agent/render.py --yes     PAID: one 360p take a clip (cap $2.00, the person's)

The prompt is lab/video_prompt run 003 (gpt-6.1-sol)'s prompt for the clip, word for word, built by that lab's own
render.py; only its `Camera:` line is swapped for the Camera agent's camera sentence (runs/E01-S04/answer.json, run 3).
Text to video, as lab/video_prompt rendered (no first frame or sheets: the scene was never written to the database).
4A-2 already has a take of the SAME prompt with today's camera ("a steady frame on a tripod"):
lab/video_prompt/runs/003_gpt-6.1-sol/takes/4A-2/take.mp4, so 4A-2 also gets a side-by-side (before | after).

Writes runs/E01-S04/takes/<slate>/: prompt_before.txt, prompt.txt, request.json, take.mp4, usage.json, stills/.
Cost counted at the 720p rate ($0.10/s; 360p has no list price). A clip with a take is never made again.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
VP = ROOT / "lab" / "video_prompt"
SLATES = ("4A-2", "4C-1", "4E-2")
CAP_USD = 2.00
ANSWER = HERE / "runs" / "E01-S04" / "answer.json"
OUT = HERE / "runs" / "E01-S04" / "takes"


def vp_render():  # lab/video_prompt/render.py (it imports that lab's run.py as `run`)
    spec = importlib.util.spec_from_file_location("vp_render", VP / "render.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def side_by_side(before: Path, after: Path, out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    label = "drawtext=text='{t}':x=12:y=12:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6"
    subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(before), "-i", str(after), "-filter_complex",  # noqa: S603
                    f"[0:v]scale=640:360,{label.format(t='TODAY - static')}[a];"
                    f"[1:v]scale=640:360,{label.format(t='CAMERA AGENT')}[b];[a][b]hstack=inputs=2[v]",
                    "-map", "[v]", "-map", "1:a?", "-shortest", str(out)], check=False)


# Re-wordings of the float (2026-11-20): the agent's "subtle handheld frame gently floating and swaying" came out as
# still as the tripod take (16 px vs 12 px). Same clip, same prompt, only the Camera: line differs.
VARIANTS = {
    "4A-2_handheld": "Eye-level waist-up two-shot, handheld camera with a slight natural shake: the frame moves a "
                     "little all the time, never still, like a documentary filmed by hand.",
    "4A-2_drift": "Eye-level waist-up two-shot, the camera drifts slowly sideways to the right through the whole "
                  "exchange, one gentle continuous move, keeping both of them in frame.",
    # run 4 (dialogue default = real slow moves): the agent's own sentence for 4A-2, word for word
    "4A-2_push": "In an eye-level waist-up two-shot, the camera slowly pushes closer to both of them through his "
                 "answer and her next question, then comes to rest.",
}
CAP_VARIANTS_USD = 1.20  # the person's yes for this re-test, 2026-11-20


def variants(r, world, aspect: str, send: bool) -> int:
    todo = []
    for name, sentence in VARIANTS.items():
        slate = name.split("_")[0]
        before, seconds = r.prompt_for(world, "003_gpt-6.1-sol", slate)
        after, n = re.subn(r"^Camera: .*$", lambda _m: f"Camera: {sentence}", before, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{slate}: no Camera: line")
        out = OUT / name
        out.mkdir(parents=True, exist_ok=True)
        req = r.body(after, seconds, aspect)
        (out / "prompt.txt").write_text(after, encoding="utf-8")
        (out / "request.json").write_text(json.dumps(req, indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{name}: {seconds} s  Camera: {sentence}{'  [have take]' if have else ''}")
        if not have:
            todo.append((name, req, out, seconds))
    cost = sum(s for *_, s in todo) * r.RATE_720P
    print(f"{len(todo)} take(s), ceiling ~${cost:.2f} (cap ${CAP_VARIANTS_USD:.2f})")
    if not send:
        return 0
    if cost > CAP_VARIANTS_USD + 1e-9:
        print("refused: past the cap")
        return 1
    for name, req, out, seconds in todo:
        usage = r.send(req, out, seconds)
        print(f"  {name} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--variants", action="store_true", help="the float re-wordings of 4A-2 instead")
    args = ap.parse_args()
    if args.variants:
        r = vp_render()
        world = r.lab.load()
        aspect = "16:9" if world["prod"].aspect_ratio in ("16:9", "") else world["prod"].aspect_ratio
        return variants(r, world, aspect, args.yes)
    r = vp_render()
    world = r.lab.load()
    aspect = "16:9" if world["prod"].aspect_ratio in ("16:9", "") else world["prod"].aspect_ratio
    cam = {c["slate"]: c for c in json.loads(ANSWER.read_text(encoding="utf-8"))["answer"]["clips"]}
    todo = []
    for slate in SLATES:
        before, seconds = r.prompt_for(world, "003_gpt-6.1-sol", slate)
        c = cam[slate]
        line = f"Camera: {c['camera_sentence']}"
        after, n = re.subn(r"^Camera: .*$", lambda _m: line, before, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{slate}: no Camera: line in the prompt")
        out = OUT / slate
        out.mkdir(parents=True, exist_ok=True)
        req = r.body(after, seconds, aspect)
        (out / "prompt_before.txt").write_text(before, encoding="utf-8")
        (out / "prompt.txt").write_text(after, encoding="utf-8")
        (out / "request.json").write_text(json.dumps(req, indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{slate}: {seconds} s; {c['support']} {c['move']} {c['speed']}{'  [have take, skipped]' if have else ''}")
        print(f"   before: {re.search(r'^Camera: .*$', before, re.M).group(0)}")  # type: ignore[union-attr]
        print(f"   after:  {line}")
        if not have:
            todo.append((slate, req, out, seconds))
    cost = sum(s for *_, s in todo) * r.RATE_720P
    print(f"{len(todo)} take(s), ceiling ~${cost:.2f} at the 720p rate (cap ${CAP_USD:.2f})")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to make the takes.")
        return 0
    if cost > CAP_USD:
        print("refused: past the cap")
        return 1
    for slate, req, out, seconds in todo:
        usage = r.send(req, out, seconds)
        print(f"  {slate} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    old = VP / "runs" / "003_gpt-6.1-sol" / "takes" / "4A-2" / "take.mp4"
    if old.exists() and (OUT / "4A-2" / "take.mp4").exists():
        side_by_side(old, OUT / "4A-2" / "take.mp4", OUT / "4A-2" / "before_after.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
