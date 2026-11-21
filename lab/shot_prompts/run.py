"""shot_prompts lab (2026-11-20): ONE agent writes a shot's FIRST FRAME and its VIDEO prompt together, from one
opening state, so the take starts on the frame and both say the same thing (the person's ask, 2026-11-20). Tested on
the person's own scene (DB, read only) with the Camera agent's designs from lab/camera_moves.

    .venv/Scripts/python.exe lab/shot_prompts/run.py --slates 2A-1,2B-1,2H-1                brief only (free)
    .venv/Scripts/python.exe lab/shot_prompts/run.py --slates ... --write --yes             PAID: the agent (+1 repair)
    .venv/Scripts/python.exe lab/shot_prompts/run.py --slates ... --paint --yes             PAID: gpt-image-2 medium
    .venv/Scripts/python.exe lab/shot_prompts/run.py --slates ... --render --yes            PAID: Omni 360p, r2v
    .venv/Scripts/python.exe lab/shot_prompts/run.py --slates ... --report                  report.md (free)

Separate from every build (plan/2026-11-20b/c): nothing in src/ changes, nothing is written to the database. Inputs:
fetch.py (GET only). Code keeps what it owns in the product: the reference citations and identity lines (frame), the
exact spoken words, the register line, the camera sentence (the Camera agent's), clean frame and text rules (video).
Caps (the person's, 2026-11-20): OpenAI $0.60 (agent + images), Omni $2.00 (720p ceiling rate).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "src" / "services" / "video_render")]

MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = {"in": 2.00, "cached": 0.10, "out": 10.00}
IMAGE_PRICE = {"in": 8.00, "cached": 2.00, "out": 30.00}  # contracts/costs.py gpt-image-2 ("confirm")
IMAGE_WORST = 0.12  # a medium 1024x1536 frame with 4-6 references, worst case
MAX_OUT = 12000
RATE_720P = 0.10
CAPS = {"openai": 0.60, "omni": 2.40}  # omni +$0.40 for the person's 2I-1 take (2026-11-20, "generate Shot 2I-1")
SCENE = ROOT / "lab" / "camera_moves" / "runs" / "db_url_scene" / "scene.json"
CAMERA = ROOT / "lab" / "camera_moves" / "runs" / "db_url_scene" / "answer.json"
NL = "\n"
Row = dict[str, Any]

GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|rig|drone|rails?|camera operator)\b", re.I)
SINHALA = re.compile(r"[඀-෿]")
LINE_ID = re.compile(r"\bL\d+\b")
QUOTES = re.compile(r"[\"“”]")
STILL_BAD = re.compile(r"\b(camera (?:moves|pushes|pulls|pans|tilts|zooms|tracks|arcs|rises|creeps)|begins to|starts to)\b",
                       re.I)
ANGLE_WORDS = {"slightly_low": r"\b(low|below|looking (?:slightly )?up|up at)\b",
               "low": r"\b(low|below|looking up|up at)\b", "worms_eye": r"\b(ground|low|looking up)\b",
               "slightly_high": r"\b(high|above|looking (?:slightly )?down|down at|down on)\b",
               "high": r"\b(high|above|looking down|down at|down on)\b",
               "overhead": r"\b(overhead|above|straight down|top)\b", "dutch": r"\b(tilt|tilted|dutch|canted)\b"}
SIZE_WORDS = {"MS": r"\b(medium|waist|mid-thigh|knee)\b", "MWS": r"\b(medium[- ]wide|knee|full|wide)\b",
              "MCU": r"\b(chest|medium close)\b", "CU": r"\b(close)\b", "WIDE": r"\b(wide|full)\b",
              "TWO": r"\b(two-shot|both)\b", "INSERT": r"\b(insert|close|detail)\b"}
SPEECH = re.compile(r"\b(says|said|asks|asked|tells|replies|whispers|calls out|speaks)\b", re.I)


# ── the answer ───────────────────────────────────────────────────────────────────────────────────────────────────────


class Person(BaseModel):
    name: str
    side: Literal["left", "centre", "right"]
    facing: str
    posture: str
    hands: str
    expression: str


class Opening(BaseModel):
    people: list[Person]
    background: str
    light: str


class Frame(BaseModel):
    composition: str = Field(description="camera height and angle in physical words, lens look, framing at the "
                                         "move's start, where each person sits, foreground and depth")
    people: str
    background: str
    light: str


class Step(BaseModel):
    kind: Literal["action", "line"]
    text: str
    line_id: str
    to: str
    how: str
    listener: str


class Video(BaseModel):
    situation: str
    people: str
    flow: list[Step]
    sound: str


class ShotPrompts(BaseModel):
    opening: Opening
    frame: Frame
    video: Video


# ── the facts ────────────────────────────────────────────────────────────────────────────────────────────────────────


def secs(text: str) -> float:
    body = text.strip().strip("\"“”").strip()
    return round(1.0 + len(body.split()) / 2.6 + 0.8 * (max(1, len(re.findall(r"[.?!…]+", body))) - 1), 1)


def facts(slate: str) -> Row:
    d = json.loads(SCENE.read_text(encoding="utf-8"))
    shot = next(s for s in d["shots"] if s["slate"] == slate)
    meta = json.loads((HERE / "runs" / slate / "inputs" / "meta.json").read_text(encoding="utf-8"))
    cam = next(c for c in json.loads(CAMERA.read_text(encoding="utf-8"))["answer"]["clips"] if c["slate"] == slate)
    names = {c["code"]: c["name"] for c in d["canon"]}
    lines_all = d["lines"]
    # The scene was planned in LINE PARTS (plan/2026-11-20): the shot's L ids are parts of the 4 script lines, and the
    # rows' shot links point elsewhere. The exact words of the shot's parts are in its own video prompt (code wrote
    # them: `X says, "..."`), in the order of the planner's "lips move to L<n>".
    prose = (shot.get("prompt") or {}).get("prose") or ""
    said = re.findall(r"\(the [^)]*\) says, \"([^\"]+)\"|(\S[^\n]*?) says, \"([^\"]+)\"", prose)
    words = [a or c for a, _b, c in said]
    ids = list(dict.fromkeys(re.findall(r"lips move to (L\d+)", json.dumps(shot.get("ir") or {}))))
    speaker = next((names.get(s.get("id")) for s in (shot.get("ir") or {}).get("subjects") or []
                    if "lips move" in str(s.get("action", "")).lower()), "")
    spoken = [{"lid": lid, "speaker": speaker, "text": w, "delivery": ""} for lid, w in zip(ids, words)] \
        if shot.get("sound_mode") in ("dialogue", "voiceover", "sung") else []
    return {"scene": d["scene"], "shot": shot, "meta": meta, "camera": cam, "names": names, "lines": lines_all,
            "spoken": spoken, "in_frame": [p for p in meta["people"] if p["in_frame"]]}


def words_of(text: str) -> str:
    return text.strip().strip("\"“”").strip()


def brief(f: Row) -> str:
    s, shot, cam = f["scene"], f["shot"], f["camera"]
    ir = shot.get("ir") or {}
    intent = shot.get("intent") or {}
    out = ["<scene>", f"Scene: {s.get('title')} ({s.get('heading')}). Style of the production: {f['meta']['style']}.",
           "Script, in order (context; the words are not yours to write):"]
    for b in s.get("script") or []:
        ln = next((x for x in f["lines"] if x["id"] == b.get("line_id")), None)
        if ln:
            out.append(f"{ln['speaker']}: \"{words_of(ln['text'])}\""
                       + (f" | delivery note: {ln['delivery']}" if ln.get("delivery") else ""))
        else:
            out.append(f"action: {b.get('text', '')}")
    out += ["</scene>", "", f"<shot slate=\"{shot['slate']}\">",
            f"Role {shot.get('role')}; the planner's size {shot.get('framing')}; take {shot.get('duration_s')} s; "
            f"sound {shot.get('sound_mode')}.",
            f"What it is for: {intent.get('purpose', '')} Story: {intent.get('story', '')} Feeling: "
            f"{intent.get('emotional_beat', '')}",
            f"What we see (planner): {intent.get('what_we_see', '')}",
            f"Setting: {ir.get('setting', '')}", f"Light: {ir.get('lighting', '')}"]
    for sub in ir.get("subjects") or []:
        who = f["names"].get(sub.get("id"), sub.get("id"))
        out.append(f"In frame: {who}. Where: {sub.get('position', '')}. Does: {sub.get('action', '')}")
    for p in f["in_frame"]:
        out.append(f"{p['name']} wears (look sheet attached): {p['look'].get('outfit', '')}")
    ff = ir.get("first_frame") or {}
    if ff:
        out.append(f"Planner's opening picture: {ff.get('composition', '')} | {'; '.join(ff.get('subjects') or [])}")
    if ir.get("beats"):
        out.append("Beats: " + " | ".join(f"{b.get('time', '')}: {b.get('action', '')} ({b.get('performance', '')})"
                                          for b in ir["beats"]))
    if f["spoken"]:
        out.append("Lines SPOKEN in this clip (each exactly once in your flow, in this order):")
        out += [f"- {ln['lid']}: {ln['speaker']}, about {secs(ln['text'])} s (\"{words_of(ln['text'])}\": context, "
                f"never yours to write)" for ln in f["spoken"]]
    else:
        out.append("Nobody speaks in this clip.")
    out += ["</shot>", "", "<camera> (the Camera agent's design: keep it)",
            f"Opens on: {cam['opens_on']}. Lands on: {cam['lands_on']} ({cam['end_size']}).",
            f"Angle {cam['angle']}, height {cam['height']}" + (f" ({cam['angle_reason']})" if cam["angle_reason"]
                                                                 else "") + ".",
            f"Lens {cam['lens']} at {cam['aperture']}; focus {cam['focus']}; composition {cam['composition']} "
            f"({cam['composition_note']}).",
            f"Move: {cam['move']} {cam['direction']}, {cam['speed']}, {cam['start_s']}-{cam['end_s']} s, on "
            f"{cam['trigger']}.",
            f"The video's camera line (code puts it in): {cam['camera_sentence']}", "</camera>"]
    return NL.join(out)


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────────


def sentences_with(text: str, name: str) -> list[str]:
    first = name.split("(")[0].strip()
    return [s for s in re.split(r"(?<=[.;])\s+", text) if first.lower() in s.lower()]


def check(a: ShotPrompts, f: Row) -> list[str]:
    faults: list[str] = []
    want = {p["name"] for p in f["in_frame"]}
    got = {p.name for p in a.opening.people}
    if got != want:
        faults.append(f"opening: people {sorted(got)} but the shot shows {sorted(want)}")
    for p in a.opening.people:
        first = p.name.split("(")[0].strip()
        for where, text in (("frame", f"{a.frame.composition} {a.frame.people}"), ("video", a.video.people)):
            if first.lower() not in text.lower():
                faults.append(f"{where}: {p.name} is in the opening but not named here")
                continue
            if p.side in ("left", "right"):
                other = "right" if p.side == "left" else "left"
                said = " ".join(sentences_with(text, p.name))
                if re.search(rf"\b{other}\b", said) and not re.search(rf"\b{p.side}\b", said):
                    faults.append(f"{where}: {p.name} is on the {other} here but on the {p.side} in the opening")
    cam = f["camera"]
    comp = a.frame.composition
    if cam["angle"] in ANGLE_WORDS and not re.search(ANGLE_WORDS[cam["angle"]], comp, re.I):
        faults.append(f"frame: the design's angle is {cam['angle']} ({cam['height']}) but the composition never says "
                      f"so in physical words")
    size = str(f["shot"].get("framing") or "")
    if size in SIZE_WORDS and not re.search(SIZE_WORDS[size], comp, re.I):
        faults.append(f"frame: the shot opens {size} but the composition does not say that framing")
    frame_text = " ".join(a.frame.model_dump().values())
    if (w := STILL_BAD.search(frame_text)):
        faults.append(f"frame: a still has no motion ('{w.group(0)}')")
    video_text = " ".join([a.video.situation, a.video.people, a.video.sound]
                          + [f"{s.text} {s.to} {s.how} {s.listener}" for s in a.video.flow])
    for where, text in (("frame", frame_text), ("video", video_text)):
        if (g := GEAR.search(text)):
            faults.append(f"{where}: names gear ('{g.group(0)}')")
        if SINHALA.search(text) or LINE_ID.search(text) or QUOTES.search(text):
            faults.append(f"{where}: Sinhala, a line id or quotation marks in your text")
    want_lines = [ln["lid"] for ln in f["spoken"]]
    got_lines = [s.line_id for s in a.video.flow if s.kind == "line"]
    if got_lines != want_lines:
        faults.append(f"video: lines {got_lines}, the clip speaks {want_lines} (each once, in order)")
    if not f["spoken"] and SPEECH.search(re.sub(r"\b(nobody|no one|no-one|none) (speaks|says)\b", "", video_text,
                                                flags=re.I)):
        faults.append("video: somebody speaks in a clip where nobody speaks")
    return faults


# ── the prompts (code's part, as the product writes it) ──────────────────────────────────────────────────────────────


def references(f: Row) -> list[tuple[str, str]]:
    """(file, what it is) in the order attached to the image model."""
    out = []
    for p in f["in_frame"]:
        out.append((f"face_{p['code']}.png", f"the face sheet for {p['name']}"))
        out.append((f"look_{p['code']}.png", f"the look sheet for {p['name']}"))
    for pl in f["meta"]["places"]:
        out.append((f"place_{pl['n']}.png", f"the location plate for {pl['name']}"))
    return out


def frame_prompt(a: ShotPrompts, f: Row) -> str:
    refs = references(f)
    cite = "; ".join(f"image {n} is {what}" for n, (_, what) in enumerate(refs, 1))
    ident = []
    for p in f["in_frame"]:
        lk = p["look"]
        ident.append(f"{p['name']}: {str(p['appearance']).strip(' .')}; as in their look sheet: "
                     f"{'; '.join(f'{k} {v.strip(chr(32) + chr(46))}' for k, v in lk.items() if k != 'name' and v)}")
    return " ".join([
        f"{f['meta']['style']}.",
        f"Reference images, in order: {cite}. Match them exactly: the same faces, hair, skin tone and build, the same "
        "place. Faces come ONLY from the face sheets, clothes ONLY from the look sheets, the place and its fixtures "
        "from the location plates (not their light or time of day). Do not redesign anyone.",
        f"This shot: {a.frame.composition}", f"People: {a.frame.people}", "Who they are: " + " ".join(ident) + ".",
        f"Background: {a.frame.background}", f"Light: {a.frame.light}",
        "Nobody looks into the lens. The people, place and everyday details are Sri Lankan. Represent interface text "
        "areas with simple geometric bars rather than lettering. 9:16 vertical framing. A single still frame: no "
        "watermark, no captions, no collage, no split panels, no words, numbers or logos.",
    ])


def video_prompt(a: ShotPrompts, f: Row) -> str:
    from contracts import on_screen_text

    by_id = {ln["lid"]: ln for ln in f["spoken"]}
    flow = []
    for s in a.video.flow:
        if s.kind == "action":
            flow.append(s.text.strip())
            continue
        ln = by_id.get(s.line_id)
        if not ln:
            continue
        block = [f"{ln['speaker']}, to {s.to.strip()}, {s.how.strip().rstrip('.:')}:", f"\"{words_of(ln['text'])}\""]
        if s.listener.strip():
            block.append(s.listener.strip().rstrip(".") + ".")
        flow.append(NL.join(block))
    talk = ("They speak casual, everyday spoken Sinhala, the way people really talk: not an interview, not a speech, "
            "nobody looks at the camera. Only these words are spoken, only by the people named; English words in a "
            "line are said as Sri Lankans say them.") if f["spoken"] else \
        "Nobody speaks in this clip: no dialogue, no voice."
    return (NL + NL).join([
        "FIRST FRAME\nThe clip opens on the supplied first frame and stays true to it: the same faces, hair, wardrobe, "
        "place, light, positions and camera angle.",
        f"SITUATION\n{a.video.situation.strip()}", f"PEOPLE\n{a.video.people.strip()}",
        "ACTION & DIALOGUE\n" + NL.join(flow) + NL + NL + talk,
        f"CAMERA\nCamera: {f['camera']['camera_sentence']}", f"SOUND\n{a.video.sound.strip()}",
        "RULES\nClean frame: no captions, no subtitles, no watermarks. " + on_screen_text.VIDEO,
        f"FORMAT\nAspect ratio 9:16. Duration {f['shot']['duration_s']} seconds. Ends on a cut.",
    ])


# ── money ────────────────────────────────────────────────────────────────────────────────────────────────────────────


class Wallet:
    def __init__(self, kind: str) -> None:
        self.kind, self.cap = kind, CAPS[kind]
        self.file = HERE / "runs" / f"spend_{kind}.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"usd": 0.0,
                                                                                                    "calls": []}

    def allow(self, worst: float, what: str) -> bool:
        ok = self.data["usd"] + worst <= self.cap + 1e-9
        print(f"  {self.kind}: ${self.data['usd']:.4f} spent; {what} at worst ${worst:.3f}; cap ${self.cap:.2f}"
              f"{'' if ok else ' -> REFUSED'}")
        return ok

    def add(self, what: str, usd: float, detail: Row | None = None) -> None:
        self.data["usd"] = round(self.data["usd"] + usd, 5)
        self.data["calls"].append({"what": what, "usd": round(usd, 5), **({"detail": detail} if detail else {})})
        self.file.write_text(json.dumps(self.data, indent=1), encoding="utf-8")


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


# ── the steps ────────────────────────────────────────────────────────────────────────────────────────────────────────


def write(slate: str, client: Any, wallet: Wallet) -> None:
    from hiru_ai.core.tokens import tokens_of

    out = HERE / "runs" / slate
    if (out / "answer.json").exists():
        print(f"{slate}: already written")
        return
    f = facts(slate)
    system = (HERE / "system.md").read_text(encoding="utf-8")
    text = brief(f)
    tok = tokens_of(system) + tokens_of(text)
    if not wallet.allow((tok * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6, f"{slate} agent"):
        return
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    calls, first = 0, []
    a: ShotPrompts | None = None
    for attempt in range(2):
        started = time.monotonic()
        resp = client.responses.parse(model=MODEL, reasoning={"effort": EFFORT}, input=messages,
                                      text_format=ShotPrompts, max_output_tokens=MAX_OUT)
        u = resp.usage
        cached = getattr(u.input_tokens_details, "cached_tokens", 0) or 0
        usd = ((u.input_tokens - cached) * PRICE["in"] + cached * PRICE["cached"] + u.output_tokens * PRICE["out"]) / 1e6
        wallet.add(f"{slate} agent{' repair' if attempt else ''}", usd, {"in": u.input_tokens, "out": u.output_tokens})
        calls += 1
        a = resp.output_parsed
        faults = check(a, f)
        print(f"  {slate}: call {attempt + 1}, ${usd:.4f}, {time.monotonic() - started:.0f} s, {len(faults)} fault(s)")
        if attempt == 0:
            first = faults
        if not faults:
            break
        if attempt == 0 and wallet.allow((tok * 1.5 * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6, f"{slate} repair"):
            messages += [{"role": "assistant", "content": resp.output_text},
                         {"role": "user", "content": "Code checked your answer and found:\n- " + "\n- ".join(faults)
                          + "\nAnswer again, complete, with these fixed and nothing else changed."}]
        else:
            break
    assert a is not None
    out.mkdir(parents=True, exist_ok=True)
    (out / "brief.txt").write_text(f"{system}\n\n=== user ===\n{text}", encoding="utf-8")
    (out / "answer.json").write_text(json.dumps({"answer": a.model_dump(), "first_faults": first,
                                                 "faults": check(a, f), "calls": calls}, indent=1,
                                                ensure_ascii=False), encoding="utf-8")
    (out / "frame_prompt.txt").write_text(frame_prompt(a, f), encoding="utf-8")
    (out / "video_prompt.txt").write_text(video_prompt(a, f), encoding="utf-8")


def answer_of(slate: str) -> ShotPrompts:
    return ShotPrompts.model_validate(json.loads((HERE / "runs" / slate / "answer.json").read_text(encoding="utf-8"))
                                     ["answer"])


def paint(slate: str, client: Any, wallet: Wallet) -> None:
    from contracts import safe_depiction
    from hiru_ai.adapters.images import OpenAIImages
    from hiru_ai.core.ports import Reference

    out = HERE / "runs" / slate
    if (out / "frame.png").exists():
        print(f"{slate}: frame already painted")
        return
    f = facts(slate)
    prompt = (out / "frame_prompt.txt").read_text(encoding="utf-8")
    if safe_depiction.blocking(prompt):
        print(f"{slate}: the frame prompt has blocked words; not painted")
        return
    if not wallet.allow(IMAGE_WORST, f"{slate} frame"):
        return
    refs = [Reference(data=(out / "inputs" / file).read_bytes(), mime="image/png", label=what)
            for file, what in references(f)]
    started = time.monotonic()
    pic = OpenAIImages(client, model="gpt-image-2", quality="medium")(prompt, "9:16", refs)
    usd = (pic.input_tokens * IMAGE_PRICE["in"] + pic.output_tokens * IMAGE_PRICE["out"]) / 1e6
    wallet.add(f"{slate} frame", usd, {"in": pic.input_tokens, "out": pic.output_tokens})
    (out / "frame.png").write_bytes(pic.data)
    print(f"  {slate}: frame painted, ${usd:.4f}, {time.monotonic() - started:.0f} s")


def _module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Google's Omni guide (docs.cloud.google.com …/use-reference-images-to-guide-video-generation, read 2026-11-20): the
# reference-to-video template appends this to the user's prompt. Added after our own citation block.
GOOGLE_LINE = "Use the images as references to generate the video."


def omni_request(slate: str) -> tuple[Any, Row, Path]:
    """The Omni request as it is sent (lab/omni_refs variant C: frame + sheets, reference_to_video), with Google's
    closing line; the folder it reads the pictures from."""
    out = HERE / "runs" / slate
    f = facts(slate)
    take_dir = out / "take"
    take_dir.mkdir(exist_ok=True)
    build = _module("omni_build", ROOT / "lab" / "omni_refs" / "build.py")
    meta = {"prose": (out / "video_prompt.txt").read_text(encoding="utf-8"), "aspect_ratio": "9:16",
            "duration_s": int(f["shot"]["duration_s"]),
            "people": [{"code": p["code"], "name": p["name"], "outfit": p["look"].get("outfit"),
                        "accessories": p["look"].get("accessories")} for p in f["in_frame"]]}
    req = build.request_b(meta, task="reference_to_video")
    req["prompt"] = req["prompt"].rstrip() + "\n" + GOOGLE_LINE
    (out / "omni_prompt.txt").write_text(req["prompt"], encoding="utf-8")
    return build, req, take_dir


TAKE_TIMEOUT_S = 240  # the person: a take comes back in about 3 minutes; one that hangs is stopped, not waited on


def send(build: Any, req: Row, folder: Path, *, timeout: float) -> Row:
    """lab/omni_refs `run.send` with a short limit (it waits up to 1680 s)."""
    import httpx
    from video_render.engine import omni
    from video_render.engine.transport import post_json

    key = env("GOOGLE__API_KEY")
    base = "https://generativelanguage.googleapis.com"
    started = time.monotonic()
    with httpx.Client() as client:
        response = post_json(client, f"{base}/v1beta/interactions?key={key}",
                             json=build.body(req, folder, with_bytes=True), timeout=timeout)
    outcome = omni.read_outcome(response)
    data = outcome["inline"]
    if data is None:
        omni.wait(outcome["file_name"], api_key=key, base_url=base, interval=5.0, deadline=started + timeout)
        data = omni.download(outcome["file_name"], api_key=key, base_url=base, attempts=5)
    (folder / "take.mp4").write_bytes(data)
    usage = {"interaction_id": outcome["interaction_id"], "usage": outcome["usage"],
             "tokens": omni.usage_tokens(outcome["usage"]), "seconds_waited": round(time.monotonic() - started, 1)}
    (folder / "usage.json").write_text(json.dumps(usage, indent=1), encoding="utf-8")
    return usage


def render(slate: str, wallet: Wallet) -> None:
    out = HERE / "runs" / slate
    take_dir = out / "take"
    if (take_dir / "take.mp4").exists():
        print(f"{slate}: take already made")
        return
    if not (out / "frame.png").exists():
        print(f"{slate}: no frame yet")
        return
    f = facts(slate)
    take_dir.mkdir(exist_ok=True)
    shutil.copy(out / "frame.png", take_dir / "frame.png")
    for p in f["in_frame"]:
        for kind in ("face", "look"):
            shutil.copy(out / "inputs" / f"{kind}_{p['code']}.png", take_dir / f"{kind}_{p['code']}.png")
    build, req, _ = omni_request(slate)
    (take_dir / "prompt.txt").write_text(req["prompt"], encoding="utf-8")
    secs_ = int(f["shot"]["duration_s"])
    if not wallet.allow(secs_ * RATE_720P, f"{slate} take"):
        return
    for attempt in range(2):  # Google answered 401/503 on back-to-back requests in lab/camera_moves; a retry worked
        try:
            usage = send(build, req, take_dir, timeout=TAKE_TIMEOUT_S)
            wallet.add(f"{slate} take", secs_ * RATE_720P, {"tokens": usage["tokens"]})
            print(f"  {slate}: take made in {usage['seconds_waited']} s")
            return
        except Exception as exc:  # noqa: BLE001 - a lab: report, wait, try again
            print(f"  {slate}: attempt {attempt + 1} failed: {str(exc)[:120]}")
            time.sleep(30)


def report(slates: list[str]) -> None:
    md = ["# Shot prompts lab: first frame + video from one agent", ""]
    for slate in slates:
        out = HERE / "runs" / slate
        if not (out / "answer.json").exists():
            continue
        d = json.loads((out / "answer.json").read_text(encoding="utf-8"))
        a = ShotPrompts.model_validate(d["answer"])
        cam = facts(slate)["camera"]
        md += [f"## {slate}", "", f"Camera design: opens on {cam['opens_on']}; {cam['angle']}/{cam['height']}; "
               f"{cam['move']} {cam['speed']} -> {cam['lands_on']}", "",
               f"Checks: {len(d['faults'])} fault(s) left, {len(d['first_faults'])} on the first answer "
               f"({'; '.join(d['first_faults']) or '-'})", "", "**Opening state**", ""]
        md += [f"- {p.name}: {p.side}, facing {p.facing}; {p.posture}; hands {p.hands}; {p.expression}"
               for p in a.opening.people]
        md += ["", f"**Frame**: {a.frame.composition} {a.frame.people}", "",
               f"**Video**: {a.video.situation} {a.video.people}", ""]
        md += [f"- {s.kind}: {s.text or (s.line_id + ' to ' + s.to + ', ' + s.how + ' / listener: ' + s.listener)}"
               for s in a.video.flow]
        md.append("")
    (HERE / "runs" / "report.md").write_text(NL.join(md), encoding="utf-8")
    print(f"report: {HERE / 'runs' / 'report.md'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slates", required=True)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--paint", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--omni", action="store_true", help="write runs/<slate>/omni_prompt.txt as Omni gets it (free)")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    slates = [s.strip() for s in args.slates.split(",") if s.strip()]
    if args.omni:
        for slate in slates:
            omni_request(slate)
            print(f"{slate}: {HERE / 'runs' / slate / 'omni_prompt.txt'}")
        return 0
    if not (args.write or args.paint or args.render or args.report):
        from hiru_ai.core.tokens import tokens_of

        for slate in slates:
            text = brief(facts(slate))
            (HERE / "runs" / slate).mkdir(parents=True, exist_ok=True)
            (HERE / "runs" / slate / "brief_dry.txt").write_text(text, encoding="utf-8")
            print(f"{slate}: ~{tokens_of(text)} tokens of brief")
        return 0
    if args.report:
        report(slates)
        return 0
    if not args.yes:
        print("add --yes to spend")
        return 0
    if args.write or args.paint:
        from openai import OpenAI

        client = OpenAI(api_key=env("OPENAI__API_KEY"), timeout=600)
        wallet = Wallet("openai")
        for slate in slates:
            if args.write:
                write(slate, client, wallet)
            if args.paint:
                paint(slate, client, wallet)
    if args.render:
        wallet = Wallet("omni")
        for slate in slates:
            render(slate, wallet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
