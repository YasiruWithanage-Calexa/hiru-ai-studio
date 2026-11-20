"""Natural dialogue lab (2026-11-19): does Omni Flash 1.2 speak Sinhala like a teledrama, not an interview, when the
prompt gives the SITUATION, the LISTENER, the MOOD and HOW each line is said, with the register beside the words?

    .venv/Scripts/python.exe lab/natural_dialogue/run.py              # dry: writes the requests, sends nothing
    .venv/Scripts/python.exe lab/natural_dialogue/run.py --yes        # PAID: one 360p take per prompt

Scene: Love Hour 4, father and Anudi about Kasun (lines from lab/sinhala_pace/lines.json, verbatim). Every line there
has an empty `delivery`: the product prompt says only `Father says, "..."`. Text to video, no pictures: the voice is the
question. Baseline for A: lab/sinhala_pace/runs/002_B_1b1c9eab/take.mp4 (same line, plain prompt, same model and size).

Each prompt goes to runs/<id>/: prompt.txt, request.json, and after a paid run take.mp4, usage.json, stills/.
A prompt that already has a take is skipped: never pay twice. Key: GOOGLE__API_KEY from the repo's .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "lab" / "sinhala_pace"), str(ROOT / "src" / "libs"),
                str(ROOT / "src" / "services" / "video_render")]

from run import BASE_URL, MODEL, RATE_720P, _env, stills  # noqa: E402  (the pace lab's helpers)

RESOLUTION = "360p"
ASPECT = "9:16"
BUDGET_USD = 2.00  # counted at the 720p rate; two 10 s takes are $2.00 at most, likely far less at 360p

HOME = ("Night, inside a modest middle-class home in Colombo, Sri Lanka. A dining table under a warm ceiling light, "
        "plastic chairs, a calendar on the wall.")
FATHER = "her father, a Sri Lankan man in his late fifties with greying hair and a plain white shirt"
ANUDI = "Anudi, a Sri Lankan woman in her mid-twenties with long black hair in a low ponytail"
REGISTER = ("They speak casual, everyday spoken Sinhala, the way a real family talks at home in a Sri Lankan "
            "teledrama: not an interview, not a speech, nobody looks at the camera.")
SOUND = "Sound: only their voices in the room, a ceiling fan turning, crickets outside. No music."

PROMPTS: dict[str, dict] = {
    "A": {
        "take_s": 10,
        "note": "one speaker, same line as the baseline take 002_B",
        "prompt": (
            f"{HOME}\n\n"
            f"{ANUDI[0].upper() + ANUDI[1:]}, sits across the table from {FATHER}. She has just told him that Kasun, "
            "the young man who sells food from a three-wheeler on the road, is only her friend. He does not believe "
            "her. Worried and a little hurt, not shouting, he leans forward and presses her, looking straight at "
            "her:\n"
            "\"යාළුවෙක් විතරද? ඒ ළමයට මොනවද තියෙන්නේ? තමන්ගේ කියලා හරියට තැනක්වත් නෑ.\"\n"
            "The first question is doubtful, almost a scoff; the second is sharper; the last trails off quietly as he "
            "shakes his head and looks away. Anudi listens with her eyes down, turning her phone in her hands; she "
            "does not speak.\n\n"
            f"{REGISTER}\n\n"
            "Camera: a vertical medium shot over Anudi's shoulder onto her father, handheld with a slight natural "
            "sway.\n\n"
            f"{SOUND}"
        ),
    },
    "B": {
        "take_s": 10,
        "note": "a real exchange in one clip: Anudi, then the father cuts in",
        "prompt": (
            f"{HOME}\n\n"
            f"{ANUDI[0].upper() + ANUDI[1:]}, sits across the table from {FATHER}. They are arguing quietly about "
            "Kasun, the young man she likes, who sells food from a three-wheeler on the road. A real family "
            "argument: they look at each other.\n\n"
            "Anudi, softly but stubbornly, almost pleading:\n"
            "\"එයාට හීනයක් තියෙනවා තාත්තේ.\"\n"
            "Her father answers straight after her, with a tired sigh and a shake of the head, firm but not "
            "shouting, tapping the table on the last words:\n"
            "\"හීනවලින් පවුල් ජීවත් කරන්න බෑ අනුදි. සල්ලි ඕනේ. අනාගතයක් තියෙන්න ඕනේ.\"\n"
            "While her father speaks, Anudi looks down and her jaw tightens; she says nothing more.\n\n"
            f"{REGISTER}\n\n"
            "Camera: a vertical two-shot across the table, both faces in three-quarter profile, handheld with a "
            "slight natural sway.\n\n"
            f"{SOUND}"
        ),
    },
}


def body(p: dict) -> dict:
    return {
        "model": MODEL, "input": [{"type": "text", "text": p["prompt"]}], "background": False, "store": True,
        "generation_config": {"video_config": {"task": "text_to_video"}},
        "response_format": {"type": "video", "aspect_ratio": ASPECT, "resolution": RESOLUTION,
                            "duration": f"{p['take_s']}s", "delivery": "uri"},
    }


def send(p: dict, out: Path) -> dict:
    """One paid take; everything after the POST goes through the product's own Omni module."""
    import httpx
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="send: each prompt is one PAID Omni take")
    args = ap.parse_args()
    todo = []
    for pid, p in PROMPTS.items():
        out = HERE / "runs" / pid
        out.mkdir(parents=True, exist_ok=True)
        (out / "prompt.txt").write_text(p["prompt"], encoding="utf-8")
        (out / "request.json").write_text(json.dumps(body(p), indent=1, ensure_ascii=False), encoding="utf-8")
        have = (out / "take.mp4").exists()
        print(f"{pid}: {p['note']}, {p['take_s']} s{'  [have take, skipped]' if have else ''}")
        if not have:
            todo.append((pid, p, out))
    seconds = sum(p["take_s"] for _, p, _ in todo)
    print(f"{len(todo)} take(s), {seconds} s at {RESOLUTION}, {MODEL}; ceiling ~${seconds * RATE_720P:.2f} at the 720p rate")
    if not args.yes:
        print("dry run: nothing sent. Add --yes to make the takes.")
        return 0
    if seconds * RATE_720P > BUDGET_USD + 1e-9:
        print(f"refused: past the ${BUDGET_USD:.2f} cap")
        return 1
    for pid, p, out in todo:
        usage = send(p, out)
        print(f"  {pid} done in {usage['seconds_waited']} s, tokens {usage['tokens']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
