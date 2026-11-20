"""Both plans live, rendered: the clips of the scene planned in line parts (plan/2026-11-20, line_parts run 003) with
the prompts the product's video prompt agent wrote for them (plan/2026-11-20b, runs/006_product_parts).

    .venv/Scripts/python.exe lab/video_prompt/render_parts.py          dry: writes the requests, sends nothing
    .venv/Scripts/python.exe lab/video_prompt/render_parts.py --yes    PAID: one 360p Omni take a clip

Text to video: these clips were never written to the database, so there is no first frame and no face/look sheet.
The prompt is the agent's, word for word, less its FIRST FRAME section (it points at a picture not sent). What this
checks: each part is spoken whole, at its pace, in its take; the father's phone voice across the cut 4H-1 -> 4C-2.
Writes runs/007_render_parts/<slate>/: prompt.txt, request.json, take.mp4, usage.json, stills/. A clip that already
has a take is skipped. Cost counted at the 720p rate ($0.10/s; 360p has no list price), cap $3.00 (the person's,
2026-11-20).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "sinhala_pace"), str(ROOT / "src" / "libs"),
                str(ROOT / "src" / "services" / "video_render")]

from run import MODEL, RATE_720P  # noqa: E402  (the pace lab's model and rate)

PROMPTS = HERE / "runs" / "006_product_parts" / "prompts.md"
OUT = HERE / "runs" / "007_render_parts"
SLATES = ["4A-1", "4B-1", "4H-1", "4C-2"]
RESOLUTION = "360p"
CAP_USD = 3.00


def prompts() -> dict[str, dict]:
    md = PROMPTS.read_text(encoding="utf-8")
    out = {}
    for sec in md.split("\n## ")[1:]:
        slate = sec.split(" ", 1)[0]
        text = re.search(r"```text\n(.*?)\n```", sec, re.S).group(1)  # type: ignore[union-attr]
        text = re.sub(r"\AFIRST FRAME\n.*?\n\n", "", text, flags=re.S)
        take = int(re.search(r"Duration (\d+) seconds", text).group(1))  # type: ignore[union-attr]
        aspect = re.search(r"Aspect ratio (\d+:\d+)", text).group(1)  # type: ignore[union-attr]
        out[slate] = {"prompt": text, "take_s": take, "aspect": aspect}
    return out


def body(p: dict) -> dict:
    return {
        "model": MODEL, "input": [{"type": "text", "text": p["prompt"]}], "background": False, "store": True,
        "generation_config": {"video_config": {"task": "text_to_video"}},
        "response_format": {"type": "video", "aspect_ratio": p["aspect"], "resolution": RESOLUTION,
                            "duration": f"{p['take_s']}s", "delivery": "uri"},
    }


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    every = prompts()
    todo = []
    for slate in SLATES:
        p, out = every[slate], OUT / slate
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompt.txt").write_text(p["prompt"], encoding="utf-8")
        (out / "request.json").write_text(json.dumps(body(p), indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{slate}: {p['take_s']} s {p['aspect']}{'  [have take, skipped]' if have else ''}")
        if not have:
            todo.append((slate, p, out))
    seconds = sum(p["take_s"] for _, p, _ in todo)
    print(f"{len(todo)} take(s), {seconds} s at {RESOLUTION}, {MODEL}; at most ~${seconds * RATE_720P:.2f}")
    if not a.yes:
        print("dry run: nothing sent")
        return 0
    if seconds * RATE_720P > CAP_USD + 1e-9:
        print(f"refused: past the ${CAP_USD:.2f} cap")
        return 1
    for slate, p, out in todo:
        try:
            usage = send(p, out)
        except Exception as exc:  # one failed take does not stop the others
            print(f"  {slate} FAILED: {exc}")
            continue
        print(f"  {slate} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    return 0


def send(p: dict, out: Path) -> dict:
    """One paid take; everything after the POST goes through the product's own Omni module (as lab/natural_dialogue)."""
    import time

    import httpx
    from run import BASE_URL, _env, stills
    from video_render.engine import omni
    from video_render.engine.transport import post_json

    key = _env("GOOGLE__API_KEY")
    started = time.monotonic()
    with httpx.Client() as client:
        response = post_json(client, f"{BASE_URL}/v1beta/interactions?key={key}", json=body(p), timeout=1680.0)
    outcome = omni.read_outcome(response)
    data = outcome["inline"]
    if data is None:
        omni.wait(outcome["file_name"], api_key=key, base_url=BASE_URL, interval=5.0, deadline=started + 1680)
        data = omni.download(outcome["file_name"], api_key=key, base_url=BASE_URL, attempts=5)
    (out / "take.mp4").write_bytes(data)
    usage = {"interaction_id": outcome["interaction_id"], "usage": outcome["usage"],
             "tokens": omni.usage_tokens(outcome["usage"]), "seconds_waited": round(time.monotonic() - started, 1)}
    (out / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    stills(out / "take.mp4", out / "stills", p["take_s"])
    return usage


if __name__ == "__main__":
    sys.exit(main())
