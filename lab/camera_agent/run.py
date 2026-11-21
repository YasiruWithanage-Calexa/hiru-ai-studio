"""Camera agent lab (2026-11-20): ONE reasoning agent decides everything the camera does, for a whole scene at once.

    .venv/Scripts/python.exe lab/camera_agent/run.py                         free: brief + today's camera, nothing sent
    .venv/Scripts/python.exe lab/camera_agent/run.py --yes                   PAID: one call for the scene (+1 repair)
    .venv/Scripts/python.exe lab/camera_agent/run.py --scene E01-S02 --yes   another saved Raphael scene
    .venv/Scripts/python.exe lab/camera_agent/run.py --ask 4C-1 --note "..." --yes
                                                     PAID: "Ask Camera" redo of one clip, the scene's answer as context

Why: takes come out with a static camera. Raphael writes most coverage as `locked_off`; the panel knows 5 moves and
maps the rest to Static; the prompt says "a steady, locked-off frame". The idea: the planner keeps the story (size,
people, action, lines, take), one Camera agent owns the camera, code checks it.

Scene: Api Denna v2 E01 (Raphael's saved runs, lab/llm_reader/runs/e2e/12_raphael), loaded through lab/video_prompt
(nothing in src/ changes, nothing is written to the database). Model gpt-6.1-sol, medium effort. Lab cap $1.00 in all
(runs/spend_total.json), checked against a worst case before every call.

Writes runs/<scene>/: brief.txt, answer.json, report.md (today's camera vs the agent's, clip by clip, + the checks).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab")]

import kb  # noqa: E402 - the cinematography knowledge base, read from its CSVs

MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = {"in": 2.00, "cached": 0.10, "out": 10.00}  # $ per million tokens (contracts/costs.py, "confirm")
CAP_USD = 1.00
MAX_OUT = 16000  # output tokens a call may use (reasoning included): the worst case is $0.16 a call (runs used ~6.5k)
NL = "\n"

# ── the catalogue ────────────────────────────────────────────────────────────────────────────────────────────────────

Support = Literal["locked_off", "operated", "handheld_subtle", "handheld_urgent", "shoulder", "steadicam", "gimbal",
                  "dolly", "slider", "jib", "crane", "drone", "vehicle_mount", "body_mount", "pov"]
Move = Literal["hold", "breathing", "drift", "reframe", "push_in", "slow_creep", "pull_out", "push_then_hold",
               "pull_back_reveal", "push_past_foreground", "truck_left", "truck_right", "tracking_alongside", "lead",
               "follow", "track_then_hold", "arc_left", "arc_right", "half_orbit", "orbit", "circle_two", "pan_left",
               "pan_right", "follow_pan", "whip_pan", "slow_pan_reveal", "tilt_up", "tilt_down", "tilt_reveal",
               "dutch_roll", "pedestal_up", "pedestal_down", "crane_up", "crane_down", "rising_reveal", "zoom_in",
               "zoom_out", "slow_zoom", "snap_zoom", "crash_zoom", "dolly_zoom", "aerial_establishing",
               "aerial_reveal", "aerial_pull_away", "top_down", "flyover", "whip_out", "whip_in", "focus_out",
               "focus_in", "shake"]
Speed = Literal["none", "very_slow", "slow", "medium", "fast", "snap"]
Size = Literal["ECU", "CU", "MCU", "MS", "MWS", "MLS", "WIDE", "EWS", "TWO", "OTS", "INSERT"]
Angle = Literal["eye_level", "slightly_low", "low", "slightly_high", "high", "overhead", "worms_eye", "dutch"]
Height = Literal["ground", "knee", "hip", "chest", "eye", "above_head", "aerial"]
Lens = Literal["18mm", "24mm", "28mm", "32mm", "35mm", "40mm", "50mm", "65mm", "75mm", "85mm", "100mm", "135mm"]
Aperture = Literal["f/1.8", "f/2", "f/2.8", "f/4", "f/5.6", "f/8"]
Focus = Literal["shallow_isolation", "medium", "deep", "rack_focus", "focus_follow"]
Composition = Literal["rule_of_thirds", "centred", "foreground_framing", "negative_space", "frame_within_frame",
                      "over_shoulder", "symmetric", "lead_room"]
Time = Literal["normal", "slow_motion", "timelapse", "hyperlapse"]
Axis = Literal["side_a", "side_b", "crossing_on_screen"]

STILL_MOVES = {"hold"}
LIVING = {"breathing", "drift", "reframe"}  # alive, not a visible move
FAST_MOVES = {"whip_pan", "whip_out", "whip_in", "snap_zoom", "crash_zoom", "shake", "orbit", "half_orbit",
              "circle_two", "dolly_zoom", "flyover"}
LONG_MOVES = {"half_orbit": 5.0, "orbit": 8.0, "circle_two": 6.0, "aerial_reveal": 4.0, "flyover": 4.0}
RISKY = {"half_orbit", "orbit", "circle_two", "whip_pan", "whip_out", "whip_in", "snap_zoom", "crash_zoom", "dolly_zoom",
         "dutch_roll", "focus_out", "focus_in", "push_past_foreground", "flyover", "top_down", "aerial_reveal", "shake"}
TIGHT = {"EWS": 0, "WIDE": 1, "MLS": 2, "MWS": 2, "TWO": 3, "MS": 3, "OTS": 4, "MCU": 4, "CU": 5, "INSERT": 5, "ECU": 6}
TIGHTER = {"push_in", "slow_creep", "push_then_hold", "zoom_in", "slow_zoom", "push_past_foreground", "crash_zoom",
           "snap_zoom"}
WIDER = {"pull_out", "pull_back_reveal", "zoom_out", "aerial_pull_away", "crane_up", "rising_reveal"}

GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|stabili[sz]er|rig|drone|tracks?\b(?! (?:"
                  r"her|him|them|the))|rails?|camera operator|operator)\b", re.I)
STILL_WORDS = re.compile(r"\b(unmoving|locked[- ]off|static|motionless|perfectly still|fixed frame)\b", re.I)
MOVE_WORDS = re.compile(r"\b(push(?:es|ing)?|pull(?:s|ing)?|eases?|easing|creep(?:s|ing)?|drift(?:s|ing)?|float(?:s|ing)?"
                        r"|breath(?:e|es|ing)?|sway(?:s|ing)?|track(?:s|ing)?|follow(?:s|ing)?|leads?|leading|arc(?:s|ing)?"
                        r"|circl(?:e|es|ing)|orbit(?:s|ing)?|pan(?:s|ning)?|tilt(?:s|ing)?|ris(?:e|es|ing)|lower(?:s|ing)?"
                        r"|descend(?:s|ing)?|glid(?:e|es|ing)|mov(?:e|es|ing)|zoom(?:s|ing)?|whip(?:s|ping)?|handheld"
                        r"|closer|back(?:s)? away|slides?|sliding|reframes?|reframing|shak(?:e|es|ing)|swings?|travels?)\b",
                        re.I)
TIMID = re.compile(r"\b(imperceptib\w*|barely|minute(?:ly)?|almost still|nearly still|tiny|minimal(?:ly)?)\b", re.I)
NOT_CAMERA = re.compile(r"\b(exclud\w*|no (?:people|one|person)|readable|lips? (?:clear|visible)|keep(?:ing)? (?:the|her"
                        r"|his|their) (?:face|lips|screen|hands?|phone)|visible throughout)\b", re.I)
EDIT_WORDS = re.compile(r"\b(handles?|tail|before the cut|the cut|in the edit|take|\d+(?:\.\d+)? seconds?|"
                        r"(?:one|two|three|four|five|six|seven|eight) seconds?|middle seconds?)\b", re.I)
LINE_ID = re.compile(r"\bL\d+\b")
SINHALA = re.compile(r"[඀-෿]")


class ClipCamera(BaseModel):
    slate: str
    support: Support
    move: Move
    direction: str = Field(description="a few words: toward whom/what, which way. Empty for a hold.")
    speed: Speed
    start_s: float
    end_s: float
    trigger: str = Field(description="what starts the move: a line id, a look, a beat. Empty for a hold.")
    motivation: str
    opens_on: str
    lands_on: str
    end_size: Size
    angle: Angle
    height: Height
    lens: Lens
    aperture: Aperture
    focus: Focus
    rack_from: str = Field(description="rack focus only, else empty")
    rack_to: str = Field(description="rack focus only, else empty")
    rack_at_s: float = Field(description="rack focus only, else 0")
    composition: Composition
    composition_note: str
    time: Time
    axis: Axis
    omni: Literal["works", "risky"]
    why: str
    camera_sentence: str


class SceneCamera(BaseModel):
    camera_language: str
    clips: list[ClipCamera]


class OneClip(BaseModel):
    clip: ClipCamera


# ── the world (lab/video_prompt's loader: the product's own shot input + Raphael's saved design) ─────────────────────


def video_prompt_lab(sid: str, raphael: str = "") -> Any:
    """lab/video_prompt's loader on a saved Raphael result: the e2e run's by default, or `raphael` (a fresh run)."""
    spec = importlib.util.spec_from_file_location("vp_lab", ROOT / "lab" / "video_prompt" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.SID = sid
    mod.SAVED = Path(raphael) if raphael else mod.E2E / "12_raphael" / f"{sid}.json"
    return mod


def clip_rows(vp: Any, world: dict[str, Any]) -> list[tuple[Any, dict[str, Any]]]:
    shots = sorted(world["scene"].shots, key=lambda s: s.number)
    return [(s, world["clips"][str(s.row.get("slate"))]) for s in shots]


def clips_brief(vp: Any, world: dict[str, Any]) -> str:
    short = world["short"]
    out = ["<clips>", "In cut order. SIZE is fixed (the clip opens on it)."]
    rows = clip_rows(vp, world)
    for i, (shot, clip) in enumerate(rows):
        ir = clip.get("ir") or {}
        cine = ir.get("cinematography") or {}
        spoken = vp.spoken(shot)
        out.append(f"<clip slate=\"{clip['slate']}\" n=\"{i + 1}\">")
        out.append(f"Setup {clip.get('setup')}; role {clip.get('role')}; SIZE {clip.get('size')} "
                   f"({cine.get('framing', '')}); take {shot.duration_s} s, handles {clip.get('handle_in_s', 0)} s in "
                   f"/ {clip.get('handle_out_s', 0)} s out; sound {shot.sound_mode}.")
        out.append(f"Planner's camera words (a hint): technique {clip.get('technique')}; {cine.get('camera', '')}; "
                   f"angle {clip.get('angle')}; movement: {cine.get('movement', '')}; depth: "
                   f"{cine.get('depth_of_field', '')}.")
        out.append(f"Why the planner made it: {clip.get('why', '')}")
        out.append(f"What happens: {clip.get('summary', '')}")
        for s in ir.get("subjects") or []:
            out.append(f"In frame: {s.get('description', '')} Where: {s.get('position', '')} Does: {s.get('action', '')}")
        for c in shot.heard:
            out.append(f"Only heard, never seen: {c.name}")
        if not shot.seen:
            out.append("No person in frame.")
        ff = ir.get("first_frame") or {}
        if ff:
            out.append(f"Opening picture: {ff.get('composition', '')}")
        out.append("Beats: " + " | ".join(f"{b.get('time', '')}: {b.get('action', '')}" for b in ir.get("beats") or []))
        if spoken:
            out.append("Spoken here: " + "; ".join(f"{short.get(ln.id, ln.id)} {ln.speaker.title()} "
                                                   f"(~{vp.speech_s(ln.text)} s)" for ln in spoken))
        else:
            out.append("Nobody speaks on camera in this clip.")
        offered = clip_ideas(vp, world, shot, clip)
        IDEAS[str(clip["slate"])] = [m for m, _ in offered]
        if offered:
            out.append("Ideas from the knowledge base (ideas, not orders): "
                       + " | ".join(f"{m}: {why}" for m, why in offered))
        out.append("</clip>")
    out.append("</clips>")
    return NL.join(out)


MOVES: list[str] = list(get_args(Move))
IDEAS: dict[str, list[str]] = {}  # slate -> the moves offered as ideas (for the report)
ROLE_TAGS = {"reaction": ["emotional_beat"], "master": ["establishing"], "establishing": ["establishing"],
             "insert": ["reveal"], "pov": ["reveal"], "clean_exit": ["transition"], "two_shot": ["dialogue"],
             "single": ["dialogue"]}


def clip_ideas(vp: Any, world: dict[str, Any], shot: Any, clip: dict[str, Any]) -> list[tuple[str, str]]:
    """Keyword search of the knowledge base with what the clip is for: the planner's why and summary, the intent and
    delivery of its script blocks, the scene's mood; tags from its role, whether it speaks, whether people walk."""
    p = world["packet"]
    blocks = p.get("E_blocks") or []
    said = [f"{blocks[b].get('intent', '')} {blocks[b].get('delivery_hint', '')}" for b in clip.get("blocks") or []
            if isinstance(b, int) and 0 <= b < len(blocks)]
    mood = " ".join((p.get("F_feeling") or {}).get("mood") or [])
    query = f"{clip.get('why', '')} {clip.get('summary', '')} {' '.join(said)} {mood}"
    tags = list(ROLE_TAGS.get(str(clip.get("role")), []))
    if vp.spoken(shot):
        tags.append("dialogue")
    if re.search(r"\b(walk|walks|walking|steps|leaves|approach|runs?|drives?)\b", query, re.I):
        tags.append("action")
    tags += [w for w in re.findall(r"[a-z_]+", mood.lower()) if w in {"tense", "intimate", "melancholic", "calm",
                                                                       "romantic", "ominous", "isolated", "joyful"}]
    # an idea that cannot fit the clip is noise: no fast move on a speaking face, aerials only for an exterior
    # master/exit, nothing that needs more time than the take
    exterior = str((world["packet"].get("A_scene") or {}).get("heading") or "").upper().startswith(("EXT", "I/E"))
    wide_ok = exterior and clip.get("role") in ("master", "establishing", "clean_exit")
    aerial = {m for m in MOVES if m.startswith("aerial")} | {"flyover", "top_down"}
    fit = [m for m in MOVES if not (vp.spoken(shot) and m in FAST_MOVES) and (m not in aerial or wide_ok)]
    fit = [m for m in fit if LONG_MOVES.get(m, 0) <= float(shot.duration_s)]
    return kb.ideas(query, tags, fit)


def scene_brief(vp: Any, world: dict[str, Any]) -> str:
    omni = (HERE / "omni.md").read_text(encoding="utf-8").strip()
    a = world["packet"].get("A_scene") or {}
    # some packets store a relationship as a plain sentence, not {between, state}
    a["relationships"] = [r if isinstance(r, dict) else {"between": ["them"], "state": str(r)}
                          for r in a.get("relationships") or []]
    return f"{vp.scene_brief(world)}\n\n{kb.menu(MOVES)}\n\n{clips_brief(vp, world)}\n\n{omni}"


# ── today's camera (what the product would send now) ─────────────────────────────────────────────────────────────────


def today(shot: Any, clip: dict[str, Any], scene: Any) -> tuple[str, str]:
    from contracts.camera_words import camera_words

    cam = shot.camera(scene)
    rec = shot.recommended(scene)
    try:
        words = camera_words(cam, rec, clip.get("ir") or {}, still=False)
    except Exception as exc:  # noqa: BLE001 - a lab: show the fault, keep going
        words = f"(could not build: {exc})"
    return f"{cam.movement} / {cam.speed}", words


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────────


def check_clip(c: ClipCamera, shot: Any, clip: dict[str, Any], vp: Any) -> tuple[list[str], list[str]]:
    """(faults that must be fixed, advisories for the report)."""
    faults: list[str] = []
    notes: list[str] = []
    s = c.slate
    take = float(shot.duration_s)
    size = str(clip.get("size") or "")
    speaks = bool(vp.spoken(shot))
    moving = c.move not in STILL_MOVES
    if c.move == "hold" and c.support not in ("locked_off", "operated", "pov"):
        notes.append(f"{s}: a hold on {c.support}")
    if moving and c.move not in LIVING:
        if not (0 <= c.start_s < c.end_s <= take + 1e-6):
            faults.append(f"{s}: the move runs {c.start_s}-{c.end_s} s, outside a {take:g} s take")
        need = LONG_MOVES.get(c.move)
        if need and c.end_s - c.start_s < need:
            faults.append(f"{s}: {c.move} needs at least {need:g} s, it has {c.end_s - c.start_s:g} s")
        if c.speed == "none":
            faults.append(f"{s}: {c.move} with speed none")
        if not c.trigger.strip():
            faults.append(f"{s}: {c.move} has no trigger")
    if speaks and (c.move in FAST_MOVES or c.speed in ("fast", "snap") or c.support == "handheld_urgent"):
        faults.append(f"{s}: a face speaks here; {c.move}/{c.speed}/{c.support} breaks lip-sync")
    if speaks and c.time != "normal":
        faults.append(f"{s}: {c.time} with a spoken line")
    if size in TIGHT and c.end_size in TIGHT:
        a, b = TIGHT[size], TIGHT[c.end_size]
        if c.move in TIGHTER and b < a or c.move in WIDER and b > a:
            faults.append(f"{s}: {c.move} from {size} cannot land on {c.end_size}")
        if c.move not in TIGHTER | WIDER and abs(b - a) > 1:
            faults.append(f"{s}: {c.move} keeps the size, but it lands on {c.end_size} from {size}")
    sent = c.camera_sentence
    if (g := GEAR.search(sent)):
        faults.append(f"{s}: the camera sentence names gear ('{g.group(0)}'), the video model draws it")
    if LINE_ID.search(sent) or SINHALA.search(sent):
        faults.append(f"{s}: the camera sentence has a line id or Sinhala")
    if (w := EDIT_WORDS.search(sent)):
        faults.append(f"{s}: the camera sentence uses an edit/clock word ('{w.group(0)}') the video model does not "
                      f"know; say it by what happens on screen")
    if len(sent) > 200:
        faults.append(f"{s}: the camera sentence is {len(sent)} characters (max 200)")
    if (w := TIMID.search(f"{sent} {c.direction}")):
        faults.append(f"{s}: '{w.group(0)}' reads as no movement to the video model; make the motion visible")
    if (w := NOT_CAMERA.search(sent)):
        faults.append(f"{s}: the camera sentence carries a picture rule ('{w.group(0)}'); camera only")
    if c.lens != str(clip.get("lens") or c.lens):
        notes.append(f"{s}: lens {clip.get('lens')} -> {c.lens} (the frame brief must follow)")
    if moving and (w := STILL_WORDS.search(sent)):
        faults.append(f"{s}: the camera moves ({c.move}) but the sentence says '{w.group(0)}'")
    if moving and not MOVE_WORDS.search(sent):
        faults.append(f"{s}: the camera moves ({c.move}) but the sentence has no move in it")
    if not moving and c.support == "locked_off" and (w := MOVE_WORDS.search(sent)) and not STILL_WORDS.search(sent):
        faults.append(f"{s}: a locked-off hold, but the sentence says '{w.group(0)}'")
    if c.move in RISKY and c.omni != "risky":
        notes.append(f"{s}: {c.move} is on the risky list but marked works")
    if c.focus == "rack_focus" and not (c.rack_from and c.rack_to and 0 < c.rack_at_s < take):
        faults.append(f"{s}: rack focus without from/to/time inside the take")
    return faults, notes


def check_scene(a: SceneCamera, rows: list[tuple[Any, dict[str, Any]]], vp: Any) -> tuple[list[str], list[str]]:
    faults: list[str] = []
    notes: list[str] = []
    want = [str(c["slate"]) for _, c in rows]
    got = [c.slate for c in a.clips]
    if got != want:
        faults.append(f"answer slates {got} != the clips in order {want}")
    by = {c.slate: c for c in a.clips}
    for shot, clip in rows:
        c = by.get(str(clip["slate"]))
        if c:
            f, n = check_clip(c, shot, clip, vp)
            faults += f
            notes += n
    setups: dict[str, set[str]] = {}
    for _, clip in rows:
        c = by.get(str(clip["slate"]))
        if c:
            setups.setdefault(str(clip.get("setup")), set()).add(c.support)
    for letter, sup in setups.items():
        if len(sup) > 1:
            notes.append(f"setup {letter}: supports differ across its clips ({', '.join(sorted(sup))})")
    n = len(a.clips) or 1
    # measured 2026-11-20: Omni renders a float (breathing/drift) as a still frame, so floats count as holds
    still = sum(1 for c in a.clips if c.move in STILL_MOVES | LIVING)
    if still > max(1, n // 4):
        faults.append(f"scene: {still} of {n} clips are holds or floats, which render still (at most {max(1, n // 4)})")
    moves = Counter(c.move for c in a.clips if c.move not in STILL_MOVES | LIVING)
    for m, k in moves.items():
        if n > 6 and k * 3 > n + 2:  # about a third, one or two over allowed for small scenes
            faults.append(f"scene: {m} on {k} of {n} clips; vary the moves (about a third at most)")
    seq = [c.move for c in a.clips]
    for i in range(len(seq) - 2):
        if seq[i] == seq[i + 1] == seq[i + 2] and seq[i] not in STILL_MOVES:
            notes.append(f"{a.clips[i].slate}-{a.clips[i + 2].slate}: {seq[i]} three clips in a row")
    axes = Counter(c.axis for c in a.clips if c.axis != "crossing_on_screen")
    if len(axes) > 1:
        notes.append(f"axis changes in the scene without a crossing on screen: {dict(axes)}")
    return faults, notes


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────────────


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def dollars(u: dict[str, int]) -> float:
    fresh = u["input"] - u["cached"]
    return (fresh * PRICE["in"] + u["cached"] * PRICE["cached"] + u["output"] * PRICE["out"]) / 1e6


class Wallet:
    def __init__(self) -> None:
        self.file = HERE / "runs" / "spend_total.json"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.data = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else {"usd": 0.0,
                                                                                                    "calls": []}

    def allow(self, tokens_in: int) -> bool:
        worst = (tokens_in * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6
        ok = self.data["usd"] + worst <= CAP_USD
        print(f"  wallet: ${self.data['usd']:.4f} spent; this call at worst ${worst:.3f}; cap ${CAP_USD:.2f}"
              f"{'' if ok else ' -> REFUSED'}")
        return ok

    def add(self, what: str, usage: dict[str, int]) -> float:
        usd = dollars(usage)
        self.data["usd"] = round(self.data["usd"] + usd, 5)
        self.data["calls"].append({"what": what, "usage": usage, "usd": round(usd, 5)})
        self.file.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        return usd


def ask(client: Any, messages: list[dict[str, str]], fmt: type[BaseModel]) -> tuple[Any, dict[str, int], str, float]:
    started = time.monotonic()
    resp = client.responses.parse(model=MODEL, reasoning={"effort": EFFORT}, input=messages, text_format=fmt,
                                  max_output_tokens=MAX_OUT)
    u = resp.usage
    usage = {"input": u.input_tokens, "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "output": u.output_tokens,
             "reasoning": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0}
    return resp.output_parsed, usage, resp.output_text, round(time.monotonic() - started, 1)


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def coverage() -> None:
    """runs/coverage.md: every move in the catalogue, how often each run used it, and the ones never used."""
    runs = sorted(p for p in (HERE / "runs").iterdir() if (p / "answer.json").exists())
    used = {r.name: Counter(c["move"] for c in json.loads((r / "answer.json").read_text(encoding="utf-8"))["answer"]
                            ["clips"]) for r in runs}
    md = ["# Moves used across runs", "", "| Move | " + " | ".join(used) + " |",
          "|---|" + "---|" * len(used)]
    for m in MOVES:
        if any(u.get(m) for u in used.values()):
            md.append(f"| {m} | " + " | ".join(str(u.get(m, "")) for u in used.values()) + " |")
    never = [m for m in MOVES if not any(u.get(m) for u in used.values())]
    md += ["", f"Used: {len(MOVES) - len(never)} of {len(MOVES)}. Never used ({len(never)}): {', '.join(never)}"]
    (HERE / "runs" / "coverage.md").write_text(NL.join(md), encoding="utf-8")


def report(out: Path, a: SceneCamera, rows: list[tuple[Any, dict[str, Any]]], faults: list[str], notes: list[str],
           meta: dict[str, Any]) -> None:
    by = {c.slate: c for c in a.clips}
    moves = Counter(c.move for c in a.clips)
    still = sum(1 for c in a.clips if c.move in STILL_MOVES)
    living = sum(1 for c in a.clips if c.move in LIVING)
    real = len(a.clips) - still - living
    today_static = sum(1 for s, _ in rows if s.camera(meta["scene"]).movement == "Static")
    md = [f"# Camera agent: {meta['sid']}", "",
          f"Model {MODEL} ({EFFORT}); {meta['calls']} call(s); ${meta['usd']:.4f}; {meta['seconds']} s.", "",
          f"**Camera language:** {a.camera_language}", "",
          f"Today: {today_static} of {len(rows)} clips Static on the panel. Agent: {still} held still, {living} alive "
          f"(breathing/drift/reframe), {real} with a real move.", "",
          "Moves: " + ", ".join(f"{k} x{v}" for k, v in moves.most_common()), "",
          f"## Checks: {len(faults)} fault(s) left, {len(meta['first_faults'])} on the first answer", ""]
    md += [f"- FAULT {f}" for f in faults] or ["- none left"]
    if meta["first_faults"]:
        md += ["", "First answer's faults (sent back once):"] + [f"- {f}" for f in meta["first_faults"]]
    md += ["", "Advisories:"] + ([f"- {n}" for n in notes] or ["- none"])
    md += ["", "## Clip by clip", ""]
    for shot, clip in rows:
        c = by.get(str(clip["slate"]))
        panel, words = today(shot, clip, meta["scene"])
        md.append(f"### {clip['slate']} · {clip.get('role')} · {clip.get('size')} · {shot.duration_s} s · "
                  f"{'speaks' if c and shot.sound_mode == 'dialogue' else shot.sound_mode}")
        md.append(f"- **Planner:** {clip.get('technique')} ({((clip.get('ir') or {}).get('cinematography') or {}).get('movement', '')})")
        md.append(f"- **Today's panel:** {panel}. Prompt camera: _{words}_")
        if c:
            timing = f" {c.start_s:g}-{c.end_s:g} s, on {c.trigger}" if c.move not in STILL_MOVES | LIVING else ""
            rack = f"; rack {c.rack_from} -> {c.rack_to} at {c.rack_at_s:g} s" if c.focus == "rack_focus" else ""
            md.append(f"- **Agent:** {c.support} · **{c.move}** {c.direction} · {c.speed}{timing} · lands "
                      f"{c.end_size} · {c.angle}/{c.height} · {c.lens} {c.aperture} · {c.focus}{rack} · "
                      f"{c.composition} ({c.composition_note}) · {c.axis} · omni {c.omni}")
            md.append(f"- **Opens on / lands on:** {c.opens_on} / {c.lands_on}")
            md.append(f"- **Why:** {c.why} _Motivation:_ {c.motivation}")
            md.append(f"- **Camera sentence:** \"{c.camera_sentence}\"")
            offered = IDEAS.get(c.slate, [])
            if offered:
                md.append(f"- **Knowledge-base ideas:** {', '.join(offered)} -> "
                          f"{'took ' + c.move if c.move in offered else 'chose ' + c.move + ' instead'}")
        md.append("")
    (out / "report.md").write_text(NL.join(md), encoding="utf-8")


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def main() -> int:
    from hiru_ai.core.tokens import tokens_of

    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="E01-S04")
    ap.add_argument("--ask", default="", help="a slate: redo that one clip (needs the scene's answer)")
    ap.add_argument("--note", default="", help="the person's note for --ask")
    ap.add_argument("--yes", action="store_true", help="send (PAID)")
    ap.add_argument("--raphael", default="", help="a fresh Raphael result json (default: the e2e run's)")
    ap.add_argument("--out", default="", help="run folder under runs/ (default: the scene id)")
    args = ap.parse_args()
    vp = video_prompt_lab(args.scene, args.raphael)
    world = vp.load()
    rows = clip_rows(vp, world)
    out = HERE / "runs" / (args.out or args.scene)
    out.mkdir(parents=True, exist_ok=True)
    system = (HERE / "system.md").read_text(encoding="utf-8")
    brief = scene_brief(vp, world)
    (out / "brief.txt").write_text(f"{system}\n\n=== user ===\n{brief}", encoding="utf-8")
    tok = tokens_of(system) + tokens_of(brief)
    print(f"{args.scene}: {len(rows)} clips; ~{tok} tokens in")
    for shot, clip in rows:
        panel, _ = today(shot, clip, world["scene"])
        print(f"  {clip['slate']:5} {clip.get('role'):11} {clip.get('size'):6} {shot.duration_s}s "
              f"planner {clip.get('technique'):18} today {panel}")
    wallet = Wallet()

    if args.ask:
        saved = out / "answer.json"
        if not saved.exists():
            raise SystemExit("run the scene first: --ask redoes one clip of the scene's answer")
        scene = SceneCamera.model_validate(json.loads(saved.read_text(encoding="utf-8"))["answer"])
        row = next(((s, c) for s, c in rows if str(c["slate"]) == args.ask), None)
        if row is None:
            raise SystemExit(f"no clip {args.ask}")
        current = next(c for c in scene.clips if c.slate == args.ask)
        msg = (f"{brief}\n\n<scene_camera>\n{scene.model_dump_json(indent=0)}\n</scene_camera>\n\n"
               f"The person asks for clip {args.ask} only: \"{args.note}\"\nRedesign that one clip, keeping it in the "
               f"scene's camera language and matching the clips before and after it. Answer that clip only.")
        print(f"ask {args.ask}: \"{args.note}\" (~{tokens_of(system) + tokens_of(msg)} tokens in)")
        if not args.yes or not wallet.allow(tokens_of(system) + tokens_of(msg)):
            return 0
        from openai import OpenAI

        client = OpenAI(api_key=env("OPENAI__API_KEY"))
        one, usage, _raw, secs = ask(client, [{"role": "system", "content": system}, {"role": "user", "content": msg}],
                                     OneClip)
        usd = wallet.add(f"{args.scene} ask {args.ask}", usage)
        faults, notes = check_clip(one.clip, row[0], row[1], vp)
        record = {"note": args.note, "before": current.model_dump(), "after": one.clip.model_dump(), "faults": faults,
                  "notes": notes, "usage": usage, "usd": round(usd, 5), "seconds": secs}
        (out / f"ask_{args.ask}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(record, indent=1, ensure_ascii=False))
        print(f"spent ${usd:.4f}; lab total ${wallet.data['usd']:.4f}")
        return 0

    if not args.yes:
        print("dry: nothing sent (add --yes)")
        return 0
    if (out / "answer.json").exists():
        print("already answered: delete runs/<scene>/answer.json to ask again")
        return 0
    if not wallet.allow(tok):
        return 0
    from openai import OpenAI

    client = OpenAI(api_key=env("OPENAI__API_KEY"))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": brief}]
    a, usage, raw, secs = ask(client, messages, SceneCamera)
    usd = wallet.add(f"{args.scene} scene", usage)
    calls, seconds = 1, secs
    faults, notes = check_scene(a, rows, vp)
    first = list(faults)
    print(f"  answer: ${usd:.4f}, {secs} s, {len(faults)} fault(s), usage {usage}")
    if faults and wallet.allow(tok + tokens_of(raw)):
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Code checked your answer and found:\n- " + "\n- ".join(faults)
                      + "\nAnswer again, complete (every clip), with these fixed and everything else kept."}]
        a, usage, raw, secs = ask(client, messages, SceneCamera)
        usd += wallet.add(f"{args.scene} repair", usage)
        calls, seconds = 2, seconds + secs
        faults, notes = check_scene(a, rows, vp)
        print(f"  repair: {secs} s, {len(faults)} fault(s) left, usage {usage}")
    (out / "answer.json").write_text(json.dumps(
        {"answer": a.model_dump(), "first_faults": first, "faults": faults, "notes": notes, "calls": calls,
         "seconds": seconds, "usd": round(usd, 5)}, indent=1, ensure_ascii=False), encoding="utf-8")
    report(out, a, rows, faults, notes, {"sid": args.scene, "scene": world["scene"], "calls": calls, "usd": usd, "seconds": seconds,
                                         "first_faults": first})
    coverage()
    print(f"spent ${usd:.4f}; lab total ${wallet.data['usd']:.4f}; report {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
