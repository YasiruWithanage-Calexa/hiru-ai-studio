"""Sinhala pace lab: how long does Omni Flash 1.2 really take to say a Sinhala line, against the clock's 2.2 words/s?

    .venv/Scripts/python.exe lab/sinhala_pace/run.py                      # dry: writes the requests, sends nothing
    .venv/Scripts/python.exe lab/sinhala_pace/run.py --only A,B --yes     # PAID: one 360p take per line named
    .venv/Scripts/python.exe lab/sinhala_pace/measure.py                  # free: reads every take's audio

Six real lines from the database (lines.json, read-only), 5 to 25 words: pure Sinhala and Sinhala mixed with English,
normal delivery and on the phone. Text to video, no images: pace is the question, not the face. Each take is long enough
that the line is never cut (a cut take says nothing about pace). The prompt asks for one person, a quiet room and no
music, so the audio is the voice alone and `measure.py` can find where it starts and ends.

Each line goes to `runs/<NNN>_<id>/`: request.json, prompt.txt, and after a paid run take.mp4, usage.json, stills/.
A line that already has a take is skipped: never pay twice for the same call. Key: GOOGLE__API_KEY from the repo's .env.
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
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "video_render")]

import pace  # noqa: E402

MODEL = "gemini-omni-1.2-flash"
RESOLUTION = "360p"
ASPECT = "9:16"
RATE_720P = 0.10  # $/s, contracts/costs.py (marked "confirm"); 360p is not listed, assumed no dearer
BASE_URL = "https://generativelanguage.googleapis.com"

# (lab id, dialogue_lines id prefix, take seconds, who speaks, where)
LINES: list[tuple[str, str, int, str, str]] = [
    ("A", "8ec39c7e", 8, "woman", "a quiet living room"),  # 5 w, pure Sinhala
    ("B", "1b1c9eab", 10, "man", "a quiet living room"),  # 11 w, pure Sinhala, three short questions
    ("C", "3c1570ee", 15, "man", "a quiet home office, holding a phone to his ear"),  # 14 w, on the phone
    ("D", "566d4ecd", 15, "woman", "a quiet living room"),  # 17 w, pure Sinhala, two sentences
    ("E", "ddc8a937", 15, "woman", "a quiet office"),  # 17 w, Sinhala + English words
    ("F", "ed7b81ff", 15, "man", "a quiet office"),  # 25 w, Sinhala + English words, three sentences
    ("G", "d2cf89f3", 10, "woman", "a quiet office"),  # 11 w, Sinhala + English words, two sentences
]
BUDGET_USD = 2.00  # the person's cap for this lab (2026-11-19), counted at the 720p rate


def _env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def load_lines() -> dict[str, dict]:
    rows = json.loads((HERE / "lines.json").read_text(encoding="utf-8"))
    out = {}
    for lab_id, prefix, take_s, who, where in LINES:
        row = next(r for r in rows if r["id"].startswith(prefix))
        text = row["text"].strip().strip('"').strip()
        out[lab_id] = {"lab_id": lab_id, "line_id": row["id"], "production": row["prod"], "text": text,
                       "delivery": row["delivery"] or "", "take_s": take_s, "who": who, "where": where,
                       "clock": pace.clock_estimate(text, row["delivery"] or ""), "syllables": pace.syllables(text)}
    return out


def prompt_for(line: dict) -> str:
    pronoun = "she" if line["who"] == "woman" else "he"
    her = "her" if line["who"] == "woman" else "his"
    return (
        f"Vertical medium close-up of one Sri Lankan {line['who']} in {her} thirties in "
        f"{line['where']}, soft daylight, static camera, {her} face and mouth clearly visible.\n\n"
        f"{pronoun.capitalize()} says exactly this line once, in Sinhala as written (English words as English), at a "
        f"natural, unhurried pace, as an actor in a Sri Lankan TV drama would, every word clear:\n"
        f"\"{line['text']}\"\n\n"
        f"{pronoun.capitalize()} begins about half a second in. After the last word {pronoun} stays silent and still "
        f"with a calm expression until the shot ends. No one else speaks.\n\n"
        "Sound: only this voice in a quiet room. No music, no background voices, no sound effects."
    )


def body(line: dict) -> dict:
    return {
        "model": MODEL, "input": [{"type": "text", "text": prompt_for(line)}], "background": False, "store": True,
        "response_format": {"type": "video", "aspect_ratio": ASPECT, "resolution": RESOLUTION,
                            "duration": f"{line['take_s']}s", "delivery": "uri"},
    }


def folder_for(lab_id: str, line_id: str) -> Path:
    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    found = sorted(p for p in runs.iterdir() if p.name.endswith(f"_{lab_id}_{line_id[:8]}"))
    if found:
        return found[-1]
    n = 1 + max((int(p.name[:3]) for p in runs.iterdir() if p.name[:3].isdigit()), default=0)
    return runs / f"{n:03d}_{lab_id}_{line_id[:8]}"


def stills(video: Path, out: Path, seconds: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    out.mkdir(exist_ok=True)
    for s in range(0, seconds + 1, 2):
        t = min(s, seconds - 0.1)
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video), "-frames:v", "1",  # noqa: S603
                        str(out / f"t{s:02d}.png")], check=False)


def send(line: dict, out: Path) -> dict:
    """One paid take through the product's own Omni module for everything after the POST."""
    import httpx
    from video_render.engine import omni
    from video_render.engine.transport import post_json

    key = _env("GOOGLE__API_KEY")
    started = time.monotonic()
    with httpx.Client() as client:
        response = post_json(client, f"{BASE_URL}/v1beta/interactions?key={key}", json=body(line), timeout=1680.0)
    outcome = omni.read_outcome(response)
    data = outcome["inline"]
    if data is None:
        omni.wait(outcome["file_name"], api_key=key, base_url=BASE_URL, interval=5.0, deadline=started + 1680)
        data = omni.download(outcome["file_name"], api_key=key, base_url=BASE_URL, attempts=5)
    (out / "take.mp4").write_bytes(data)
    usage = {"interaction_id": outcome["interaction_id"], "usage": outcome["usage"],
             "tokens": omni.usage_tokens(outcome["usage"]), "seconds_waited": round(time.monotonic() - started, 1)}
    (out / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    stills(out / "take.mp4", out / "stills", line["take_s"])
    return usage


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="lab ids, e.g. A,B (default: all)")
    ap.add_argument("--yes", action="store_true", help="send: each line is one PAID Omni take")
    args = ap.parse_args()
    lines = load_lines()
    pick = [x.strip().upper() for x in args.only.split(",") if x.strip()] or list(lines)
    todo = []
    for lab_id in pick:
        line = lines[lab_id]
        out = folder_for(lab_id, line["line_id"])
        out.mkdir(exist_ok=True)
        (out / "line.json").write_text(json.dumps(line, indent=1, ensure_ascii=False), encoding="utf-8")
        (out / "prompt.txt").write_text(prompt_for(line), encoding="utf-8")
        (out / "request.json").write_text(json.dumps(body(line), indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        c = line["clock"]
        print(f"{lab_id} {line['production']}: {c['words']} w, {line['syllables']['total']} syl, clock says "
              f"{c['said_s']} s to say ({c['need_s']} s take) -> {line['take_s']} s take"
              f"{'  [have take, skipped]' if have else ''}  {out.relative_to(ROOT)}")
        if not have:
            todo.append((line, out))
    seconds = sum(line["take_s"] for line, _ in todo)
    print(f"{len(todo)} take(s), {seconds} s at {RESOLUTION}, {MODEL}; ceiling ~${seconds * RATE_720P:.2f} at the 720p rate")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to make the takes.")
        return 0
    spent = sum(json.loads((p / "line.json").read_text(encoding="utf-8"))["take_s"]
                for p in (HERE / "runs").glob("*_*_*") if (p / "take.mp4").exists()) * RATE_720P
    if spent + seconds * RATE_720P > BUDGET_USD + 1e-9:
        print(f"refused: ${spent:.2f} already spent + ${seconds * RATE_720P:.2f} goes past the ${BUDGET_USD:.2f} cap")
        return 1
    for line, out in todo:
        usage = send(line, out)
        print(f"  {line['lab_id']} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
