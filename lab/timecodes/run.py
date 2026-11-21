"""timecodes lab (2026-11-21): does Google's timecode syntax ("[0-2s] ...") in ACTION & DIALOGUE, plus "A single
continuous shot, no scene cuts.", make Omni place the action and the spoken line where we ask?

A/B on the product's own requests, nothing written to the database:
  A = today's take of the shot (made by the product at 360p on 2026-11-21, scripts/camera_live.py), already paid
  B = the SAME stored render spec (frame, sheets, settings, 360p), with only the prompt changed: each step of ACTION &
      DIALOGUE prefixed with its range, and the FORMAT line "A single continuous shot, no scene cuts." instead of
      "Ends on a cut." The ranges come from gpt-6.1-sol (the shot prompter's system prompt + the timing rule), given
      the shot's own flow, take length, speech seconds and camera timing; code checks them (ONE repair).

    .venv/Scripts/python.exe lab/timecodes/run.py --shots 3D-1,3C-1            free: inputs + A measured
    .venv/Scripts/python.exe lab/timecodes/run.py --shots 3D-1,3C-1 --ranges --yes     PAID (OpenAI): the ranges
    .venv/Scripts/python.exe lab/timecodes/run.py --shots 3D-1,3C-1 --render --yes     PAID (Omni): the B takes
    .venv/Scripts/python.exe lab/timecodes/run.py --shots 3D-1,3C-1 --report           free: measure + README table

Money (the person's caps, 2026-11-21): OpenAI $0.10, Omni $1.20 (counted at the 720p ceiling, $0.10/s).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src" / "services" / "video_render"), str(ROOT / "src")]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os  # noqa: E402
import subprocess  # noqa: E402


def measured(take: Path) -> dict:
    """measure.py under the system Python (numpy is not in the project's venv)."""
    got = subprocess.run([os.environ.get("MEASURE_PY", "python"), str(HERE / "measure.py"), str(take)], capture_output=True, text=True, check=True)
    return json.loads(got.stdout.strip().splitlines()[-1])

PID = "b89f79a3-3ce6-4123-aee5-759f35c09d69"  # Love Hour 4
SCENE = "bd5a6483-0eef-4a66-afac-b60556478618"  # SCENE 03
A_TAKES = ROOT / "lab" / "camera_moves" / "runs" / "live" / "files"
MODEL, EFFORT, MAX_OUT = "gpt-6.1-sol", "medium", 4000
PRICE = {"in": 2.00, "cached": 0.10, "out": 10.00}
CAPS = {"openai": 0.10, "omni": 1.20}
RATE_720P = 0.10
SINGLE = "A single continuous shot, no scene cuts."
NL = "\n"

TIMING = """# Timing (this call)

The video model takes timecodes: each step of the clip's flow is prefixed with the seconds it plays in, "[0-1s]",
"[1-5s]". You are given the clip's flow as written, in order. Give each step its range:
- The ranges run from 0 to the take length, in order, with no gap and no overlap; whole seconds, or half seconds when a
  take of 4 s needs them.
- A spoken line's range is at least as long as its speech time (given), plus a little air. A speaking face needs a
  moment first: a line rarely starts at 0.
- Each step lasts at least 1 s; about one step per 1.5 s at most.
- Agree with the camera: a move that starts on a beat starts in that beat's range.
Answer every step, by its number."""


class StepTime(BaseModel):
    n: int
    start_s: float
    end_s: float


class Timing(BaseModel):
    steps: list[StepTime]


# ── the wallets ──────────────────────────────────────────────────────────────────────────────────────────────────────


class Wallet:
    def __init__(self, kind: str) -> None:
        self.kind, self.cap = kind, CAPS[kind]
        self.file = HERE / "runs" / f"{kind}_total.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"usd": 0.0,
                                                                                                    "calls": []}

    def allow(self, worst: float, what: str) -> bool:
        ok = self.data["usd"] + worst <= self.cap + 1e-9
        print(f"  {self.kind} wallet ${self.data['usd']:.4f}; {what} at worst ${worst:.3f}; cap ${self.cap:.2f}"
              + ("" if ok else " -> REFUSED"))
        return ok

    def add(self, what: str, usd: float, detail: dict | None = None) -> None:
        self.data["usd"] = round(self.data["usd"] + usd, 5)
        self.data["calls"].append({"what": what, "usd": round(usd, 5), **({"detail": detail} if detail else {})})
        self.file.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


# ── the inputs (GET only) ────────────────────────────────────────────────────────────────────────────────────────────


def rest() -> Any:
    from hiru_ai.adapters import supabase_rest
    from hiru_ai.core.settings import get_settings

    s = get_settings()
    return supabase_rest.Rest(s.supabase.url, s.supabase.service_role_key.get_secret_value())


def fetch(slate: str) -> dict:
    """The shot row, its stored shot prompt and camera, and the product's last render spec of it (today's A take)."""
    r = rest()
    shot = r.first("shots", {"scene_id": f"eq.{SCENE}", "slate": f"eq.{slate}", "select": "*"})
    spec = r.select("video_renders", {"shot_id": f"eq.{shot['id']}", "status": "eq.done", "select": "id,spec",
                                      "order": "created_at.desc", "limit": "1"})[0]
    out = HERE / "runs" / slate
    out.mkdir(parents=True, exist_ok=True)
    data = {"slate": slate, "take_s": int(shot["duration_s"]), "sound_mode": shot.get("sound_mode"),
            "shot_prompt": (shot.get("design") or {}).get("shot_prompt"),
            "camera": (shot.get("design") or {}).get("camera"), "beats": (shot.get("ir") or {}).get("beats"),
            "render_id": spec["id"], "spec": spec["spec"]}
    (out / "inputs.json").write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "A_prompt.txt").write_text(spec["spec"]["prose"], encoding="utf-8")
    return data


def inputs(slate: str) -> dict:
    return json.loads((HERE / "runs" / slate / "inputs.json").read_text(encoding="utf-8"))


# ── the prompt ───────────────────────────────────────────────────────────────────────────────────────────────────────


def sections(prose: str) -> list[tuple[str, str]]:
    """[(TITLE, body)] in order: a title is an upper-case line after a blank line."""
    out: list[tuple[str, str]] = []
    for block in re.split(r"\n\n(?=[A-Z][A-Z &]+\n)", prose.strip()):
        title, _, body = block.partition("\n")
        out.append((title.strip(), body))
    return out


def join(parts: list[tuple[str, str]]) -> str:
    return (NL + NL).join(f"{t}{NL}{b}" for t, b in parts)


def action_blocks(prose: str, steps: int) -> tuple[list[str], str]:
    """The ACTION & DIALOGUE body as the flow's step blocks (one per step, in order) and what follows them (the
    register / "Nobody speaks" paragraph)."""
    body = dict(sections(prose))["ACTION & DIALOGUE"]
    blocks = body.split(NL + NL)
    if len(blocks) < steps:
        raise SystemExit(f"{len(blocks)} blocks for {steps} steps")
    return blocks[:steps], (NL + NL).join(blocks[steps:])


def secs(text: str) -> float:
    from hiru_ai.steps.shot_prompt.logic import speech_s

    return speech_s(text)


def brief(d: dict) -> str:
    flow = (d["shot_prompt"] or {}).get("video", {}).get("flow") or []
    blocks, _ = action_blocks(d["spec"]["prose"], len(flow))
    cam = d["camera"] or {}
    out = [f"Take length: {d['take_s']} s. Sound: {d['sound_mode']}.",
           f"Camera: {cam.get('move', '')} {cam.get('direction', '')}, {cam.get('start_s')}-{cam.get('end_s')} s, "
           f"on {cam.get('trigger', '')}. Sentence: {cam.get('camera_sentence', '')}"]
    if d.get("beats"):
        out.append("Planner's beats: " + " | ".join(f"{b.get('time', '')}: {b.get('action', '')}"
                                                     for b in d["beats"] if isinstance(b, dict)))
    out.append("The flow, in order:")
    for n, (step, block) in enumerate(zip(flow, blocks, strict=True), 1):
        if step.get("kind") == "line":
            words = re.findall(r"\"([^\"]+)\"", block)
            out.append(f"{n}. LINE {step.get('line_id')} ({secs(words[0]) if words else '?'} s of speech): "
                       + block.split(NL)[0])
        else:
            out.append(f"{n}. ACTION: {block}")
    return NL.join(out)


def check(t: Timing, d: dict) -> list[str]:
    flow = (d["shot_prompt"] or {}).get("video", {}).get("flow") or []
    blocks, _ = action_blocks(d["spec"]["prose"], len(flow))
    take = float(d["take_s"])
    f: list[str] = []
    got = sorted(t.steps, key=lambda s: s.n)
    if [s.n for s in got] != list(range(1, len(flow) + 1)):
        return [f"answer every step 1-{len(flow)} once"]
    if got[0].start_s != 0 or abs(got[-1].end_s - take) > 1e-6:
        f.append(f"the ranges must run from 0 to {take:g} s")
    for a, b in zip(got, got[1:], strict=False):
        if abs(a.end_s - b.start_s) > 1e-6:
            f.append(f"step {a.n} ends at {a.end_s:g} s but step {b.n} starts at {b.start_s:g} s")
    for s, step, block in zip(got, flow, blocks, strict=True):
        if s.end_s - s.start_s < 1 - 1e-6:
            f.append(f"step {s.n} lasts under 1 s")
        if (s.start_s * 2) % 1 or (s.end_s * 2) % 1:
            f.append(f"step {s.n}: whole or half seconds only")
        if step.get("kind") == "line":
            words = re.findall(r"\"([^\"]+)\"", block)
            need = secs(words[0]) if words else 0
            if s.end_s - s.start_s + 0.5 < need:  # the clock is generous; half a second of slack
                f.append(f"step {s.n} speaks about {need} s of words in {s.end_s - s.start_s:g} s")
    if len(flow) > max(2, round(take / 1.5)):
        f.append(f"{len(flow)} steps in {take:g} s")
    return f


def stamp(x: float) -> str:
    return f"{x:g}"


def b_prompt(d: dict, t: Timing) -> str:
    flow = (d["shot_prompt"] or {}).get("video", {}).get("flow") or []
    blocks, rest_ = action_blocks(d["spec"]["prose"], len(flow))
    by = {s.n: s for s in t.steps}
    timed = [f"[{stamp(by[n].start_s)}-{stamp(by[n].end_s)}s] {b}" for n, b in enumerate(blocks, 1)]
    body = (NL + NL).join(timed + ([rest_] if rest_ else []))
    parts = [(title, body if title == "ACTION & DIALOGUE" else
              re.sub(r"\s*Ends on a cut\.", " " + SINGLE, b) if title == "FORMAT" else b)
             for title, b in sections(d["spec"]["prose"])]
    return join(parts)


# ── the calls ────────────────────────────────────────────────────────────────────────────────────────────────────────


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def ranges(slate: str, wallet: Wallet) -> None:
    from openai import OpenAI

    d = inputs(slate)
    out = HERE / "runs" / slate
    system = (ROOT / "src/libs/hiru_ai/agents/shot_prompter/prompts/system.md").read_text(encoding="utf-8")
    system += NL + NL + TIMING
    text = brief(d)
    (out / "ranges_brief.txt").write_text(text, encoding="utf-8")
    worst = ((len(system) + len(text)) / 3 * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6
    if not wallet.allow(worst, f"{slate} ranges"):
        return
    client = OpenAI(api_key=env("OPENAI__API_KEY"))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    faults: list[str] = []
    for attempt in range(2):
        resp = client.responses.parse(model=MODEL, reasoning={"effort": EFFORT}, input=messages, text_format=Timing,
                                      max_output_tokens=MAX_OUT)
        u = resp.usage
        cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
        usd = ((u.input_tokens - cached) * PRICE["in"] + cached * PRICE["cached"] + u.output_tokens * PRICE["out"]) / 1e6
        wallet.add(f"{slate} ranges {attempt + 1}", usd, {"in": u.input_tokens, "out": u.output_tokens})
        t = resp.output_parsed
        faults = check(t, d)
        print(f"  {slate}: ranges {[(s.n, s.start_s, s.end_s) for s in t.steps]} ${usd:.4f} faults {faults}")
        if not faults:
            break
        messages += [{"role": "assistant", "content": resp.output_text},
                     {"role": "user", "content": "Code found:\n- " + "\n- ".join(faults) + "\nAnswer again."}]
    (out / "ranges.json").write_text(json.dumps({"steps": [s.model_dump() for s in t.steps], "faults": faults},
                                                indent=1), encoding="utf-8")
    (out / "B_prompt.txt").write_text(b_prompt(d, t), encoding="utf-8")


def render(slate: str, wallet: Wallet) -> None:
    """The product's request for the stored spec (contracts.video_gen.build_request), the prose swapped for B, sent by
    the product's Omni engine (video_render.engine.omni.generate). Nothing is written to the database."""
    from contracts.video_gen import RenderSpec, build_request
    from hiru_ai.adapters.storage import SupabaseFiles
    from video_render.engine import omni

    out = HERE / "runs" / slate
    if (out / "B_take.mp4").exists():
        print(f"{slate}: B already made")
        return
    d = inputs(slate)
    spec = RenderSpec.model_validate({**d["spec"], "prose": (out / "B_prompt.txt").read_text(encoding="utf-8")})
    built = build_request(spec)
    (out / "B_request.json").write_text(json.dumps({k: v for k, v in built.items() if k != "references"} |
                                                   {"references": [{k: r[k] for k in r if k != "data"}
                                                                   for r in built["references"]]},
                                                   indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    files = SupabaseFiles(rest())
    pics = {}
    for part in built["references"]:
        if part["path"] not in pics:
            data = bytes(files.download(part["bucket"], part["path"]))
            pics[part["path"]] = (data, "image/png" if data[:4] == b"\x89PNG" else "image/jpeg")
    if not wallet.allow(d["take_s"] * RATE_720P, f"{slate} B take"):
        return
    for attempt in range(2):
        try:
            started = time.monotonic()
            got = omni.generate(built, pics, api_key=env("GOOGLE__API_KEY"),
                                base_url="https://generativelanguage.googleapis.com",
                                deadline=time.monotonic() + 300, poll_interval=5.0, download_attempts=5)
            (out / "B_take.mp4").write_bytes(got["data"])
            wallet.add(f"{slate} B take", d["take_s"] * RATE_720P,
                       {"tokens": [got["prompt_tokens"], got["completion_tokens"]]})
            print(f"  {slate}: B take in {time.monotonic() - started:.0f} s")
            return
        except Exception as exc:  # noqa: BLE001  a lab: report, wait, try again once
            print(f"  {slate}: attempt {attempt + 1} failed: {str(exc)[:160]}")
            time.sleep(20)


def report(slates: list[str]) -> None:
    rows = ["| Shot | Take | Asked ranges | Speech (audio) | Cuts | Camera path |", "|---|---|---|---|---|---|"]
    for slate in slates:
        out = HERE / "runs" / slate
        shutil.copy(A_TAKES / f"{slate}_take.mp4", out / "A_take.mp4") if not (out / "A_take.mp4").exists() else None
        asked = json.loads((out / "ranges.json").read_text(encoding="utf-8"))["steps"] if (out / "ranges.json").exists() \
            else []
        for name in ("A", "B"):
            take = out / f"{name}_take.mp4"
            if not take.exists():
                continue
            m = measured(take)
            (out / f"{name}_measure.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
            sp = m["speech"]
            said = f"{sp['first_s']}-{sp['last_s']} s" if sp.get("first_s") is not None else "none"
            want = ", ".join(f"{s['start_s']:g}-{s['end_s']:g}" for s in asked) if name == "B" else "(none: today)"
            rows.append(f"| {slate} | {name} | {want} | {said} | {m['cuts_s'] or 'none'} | {m['path_px']} px |")
    (HERE / "runs" / "results.md").write_text(NL.join(rows), encoding="utf-8")
    print(NL.join(rows))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--ranges", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    slates = [s for s in a.shots.split(",") if s]
    if (a.ranges or a.render) and not a.yes:
        raise SystemExit("paid: --yes only after the person said yes")
    for slate in slates:
        if a.ranges:
            ranges(slate, Wallet("openai"))
        elif a.render:
            render(slate, Wallet("omni"))
        elif not a.report:
            d = fetch(slate)
            print(f"{slate}: {d['take_s']} s, render {d['render_id'][:8]}")
            print(brief(d))
    if a.report:
        report(slates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
