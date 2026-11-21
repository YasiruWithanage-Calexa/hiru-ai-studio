"""camera_moves lab (2026-11-20): the Camera agent, CINEMATIC FIRST by logic (moment -> intensity -> power -> move,
angle and height), on dramatic scenes: a reveal, a vehicle, a confrontation, an arrival, a chase, plus Api Denna S04
again (angle/height before/after) and the person's own production scene (for the first-frame renders).

Separate from lab/camera_agent (plan/2026-11-20c is being built from it): nothing there or in src/ changes. The
knowledge-base menu and ideas are read through lab/camera_agent/kb.py (read only).

    .venv/Scripts/python.exe lab/camera_moves/run.py --scene ekama_s01            free: brief only
    .venv/Scripts/python.exe lab/camera_moves/run.py --scene ekama_s01 --yes      PAID: one call (+1 repair)
    .venv/Scripts/python.exe lab/camera_moves/run.py --coverage                   runs/coverage.md over every run

Scenes (sources.py): ekama_s01 (reveal), ekama_s02 (vehicle), ekama_s03 (confrontation), apidenna_s02 (arrival),
apidenna_s04 (talk: angle/height), chase (written test scene, planned by Raphael), db_url_scene (the person's).
Model gpt-6.1-sol, medium. Money: wallet.py ($1.50 OpenAI).
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
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "src")]

import sources  # noqa: E402
from wallet import Wallet  # noqa: E402

MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = {"in": 2.00, "cached": 0.10, "out": 10.00}
MAX_OUT = 16000
NL = "\n"


def _kb() -> Any:  # lab/camera_agent/kb.py, read only
    spec = importlib.util.spec_from_file_location("ca_kb", ROOT / "lab" / "camera_agent" / "kb.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


kb = _kb()

# ── the catalogue ────────────────────────────────────────────────────────────────────────────────────────────────────

Moment = Literal["reveal", "confrontation", "realisation", "pursuit", "arrival", "departure", "isolation", "intimacy",
                 "threat", "tension", "establishing", "transition", "dialogue"]
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
Size = Literal["ECU", "CU", "MCU", "MS", "MWS", "MLS", "WIDE", "EWS", "TWO", "OTS", "INSERT", "POV"]
Angle = Literal["eye_level", "slightly_low", "low", "slightly_high", "high", "overhead", "worms_eye", "dutch"]
Height = Literal["ground", "knee", "hip", "chest", "shoulder", "eye", "above_head", "aerial"]
Lens = Literal["14mm", "18mm", "24mm", "28mm", "32mm", "35mm", "40mm", "50mm", "55mm", "65mm", "75mm", "85mm", "100mm",
               "135mm"]
Aperture = Literal["f/1.4", "f/1.8", "f/2", "f/2.8", "f/4", "f/5.6", "f/8"]
Focus = Literal["shallow_isolation", "medium", "deep", "rack_focus", "focus_follow"]
Composition = Literal["rule_of_thirds", "centred", "foreground_framing", "negative_space", "frame_within_frame",
                      "over_shoulder", "symmetric", "lead_room"]
Time = Literal["normal", "slow_motion", "timelapse", "hyperlapse"]
Axis = Literal["side_a", "side_b", "crossing_on_screen"]
MOVES: list[str] = list(get_args(Move))

STILL = {"hold"}
FLOATS = {"breathing", "drift"}  # measured: render as still
# how strong a camera choice reads on screen (move family), times the speed
STRENGTH = {"hold": 0, "breathing": 0.3, "drift": 0.3, "reframe": 0.7, "slow_creep": 1, "slow_zoom": 1,
            "push_in": 2, "pull_out": 2, "push_then_hold": 2.2, "zoom_in": 2, "zoom_out": 2, "pan_left": 1.6,
            "pan_right": 1.6, "follow_pan": 1.8, "tilt_up": 1.6, "tilt_down": 1.6, "truck_left": 1.8,
            "truck_right": 1.8, "pedestal_up": 1.8, "pedestal_down": 1.8, "tracking_alongside": 2.4, "lead": 2.6,
            "follow": 2.4, "track_then_hold": 2.4, "slow_pan_reveal": 2.2, "tilt_reveal": 2.6,
            "pull_back_reveal": 2.8, "push_past_foreground": 2.8, "arc_left": 2.8, "arc_right": 2.8,
            "crane_up": 3, "crane_down": 3, "rising_reveal": 3.2, "aerial_establishing": 3, "aerial_reveal": 3.4,
            "aerial_pull_away": 3.2, "top_down": 3, "flyover": 3.4, "half_orbit": 3.6, "circle_two": 3.6,
            "orbit": 4, "dutch_roll": 3.4, "whip_pan": 3.8, "whip_out": 3.4, "whip_in": 3.4, "snap_zoom": 3.8,
            "crash_zoom": 4, "dolly_zoom": 4.2, "focus_out": 1.5, "focus_in": 1.5, "shake": 3.5}
SPEED_X = {"none": 1, "very_slow": 0.75, "slow": 1, "medium": 1.25, "fast": 1.5, "snap": 1.6}
BOLD = {"dolly_zoom", "whip_pan", "whip_out", "whip_in", "snap_zoom", "crash_zoom", "orbit", "half_orbit", "circle_two",
        "dutch_roll", "shake", "flyover"}
FAST_ON_FACE = {"whip_pan", "whip_out", "whip_in", "snap_zoom", "crash_zoom", "shake", "orbit", "half_orbit",
                "circle_two", "dolly_zoom", "flyover"}
LONG = {"half_orbit": 5.0, "orbit": 8.0, "circle_two": 6.0, "aerial_reveal": 4.0, "flyover": 4.0}
TIGHTER = {"push_in", "slow_creep", "push_then_hold", "zoom_in", "slow_zoom", "push_past_foreground", "crash_zoom",
           "snap_zoom", "dolly_zoom"}
WIDER = {"pull_out", "pull_back_reveal", "zoom_out", "aerial_pull_away", "crane_up", "rising_reveal", "top_down"}
ANGLE_MOVES = {"crane_up", "crane_down", "rising_reveal", "pedestal_up", "pedestal_down", "tilt_up", "tilt_down",
               "tilt_reveal", "top_down", "aerial_establishing", "aerial_reveal", "aerial_pull_away", "dutch_roll",
               "arc_left", "arc_right", "half_orbit", "orbit", "circle_two", "flyover"}
TIGHT = {"EWS": 0, "WIDE": 1, "MLS": 2, "MWS": 2, "TWO": 3, "MS": 3, "POV": 3, "OTS": 4, "MCU": 4, "CU": 5,
         "INSERT": 5, "ECU": 6}
# plan/2026-11-20d §6.4: variety is counted by FAMILY (push_in + push_then_hold + slow_creep are one way of moving)
FAMILY = {**{m: "forward" for m in ("push_in", "slow_creep", "push_then_hold", "zoom_in", "slow_zoom",
                                     "push_past_foreground")},
          **{m: "back" for m in ("pull_out", "pull_back_reveal", "zoom_out")},
          **{m: "travel" for m in ("truck_left", "truck_right", "tracking_alongside", "lead", "follow",
                                    "track_then_hold")},
          **{m: "arc" for m in ("arc_left", "arc_right", "half_orbit", "orbit", "circle_two")},
          **{m: "pan" for m in ("pan_left", "pan_right", "follow_pan", "whip_pan", "slow_pan_reveal", "whip_out",
                                 "whip_in")},
          **{m: "tilt" for m in ("tilt_up", "tilt_down", "tilt_reveal")},
          **{m: "vertical" for m in ("pedestal_up", "pedestal_down", "crane_up", "crane_down", "rising_reveal",
                                      "aerial_establishing", "aerial_reveal", "aerial_pull_away", "top_down",
                                      "flyover")},
          **{m: "punch" for m in ("snap_zoom", "crash_zoom", "dolly_zoom")},
          **{m: "unrest" for m in ("dutch_roll", "shake")},
          **{m: "focus" for m in ("focus_out", "focus_in")},
          "reframe": "reframe"}
SUBJECT = re.compile(r"\bthe camera\b", re.I)  # §6.3: "the camera" is the sentence's subject, never the person

GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|stabili[sz]er|rig|drone|rails?|"
                  r"camera operator|tracks\b(?! (?:her|him|them|the))|on a track)\b", re.I)
STILL_WORDS = re.compile(r"\b(unmoving|locked[- ]off|static|motionless|perfectly still|fixed frame)\b", re.I)
MOVE_WORDS = re.compile(r"\b(push(?:es|ing)?|pull(?:s|ing)?|eases?|easing|creep(?:s|ing)?|track(?:s|ing)?|"
                        r"follow(?:s|ing)?|leads?|leading|arc(?:s|ing)?|circl(?:e|es|ing)|orbit(?:s|ing)?|"
                        r"pan(?:s|ning)?|tilt(?:s|ing)?|ris(?:e|es|ing)|lower(?:s|ing)?|descend(?:s|ing)?|"
                        r"glid(?:e|es|ing)|mov(?:e|es|ing)|zoom(?:s|ing)?|whip(?:s|ping)?|handheld|closer|"
                        r"back(?:s)? away|slides?|sliding|reframes?|reframing|shak(?:e|es|ing)|swings?|travels?|"
                        r"sweeps?|races?|rushes|drops?|lifts?|cranes?|soars?|swoops?|retreats?|recedes?|"
                        r"rolls?|tips?|spins?|turns?|snaps?|dives?|flies|floats?|drifts?|backs?|chases?|runs?)\b", re.I)
TIMID = re.compile(r"\b(imperceptib\w*|barely|minute(?:ly)?|almost still|nearly still|tiny|minimal(?:ly)?)\b", re.I)
EDIT_WORDS = re.compile(r"\b(handles?|tail|before the cut|the cut|in the edit|take|\d+(?:\.\d+)? seconds?|"
                        r"(?:one|two|three|four|five|six|seven|eight) seconds?)\b", re.I)
LINE_ID = re.compile(r"\bL\d+\b")
SINHALA = re.compile(r"[඀-෿]")


class ClipCamera(BaseModel):
    slate: str
    moment: Moment
    intensity: int = Field(description="1-5 on the scene's arc")
    power: str = Field(description="who holds the power in this clip, or 'equal' / 'none'")
    support: Support
    move: Move
    direction: str
    speed: Speed
    start_s: float
    end_s: float
    trigger: str
    motivation: str
    opens_on: str
    lands_on: str
    end_size: Size
    angle: Angle
    height: Height
    angle_reason: str = Field(description="why this angle and height; empty only for eye level between equals")
    lens: Lens
    aperture: Aperture
    focus: Focus
    rack_from: str
    rack_to: str
    rack_at_s: float
    composition: Composition
    composition_note: str
    time: Time
    axis: Axis
    omni: Literal["works", "risky"]
    why: str
    camera_sentence: str


class SceneCamera(BaseModel):
    camera_language: str
    arc: str
    peak_slate: str
    clips: list[ClipCamera]


# ── the brief ────────────────────────────────────────────────────────────────────────────────────────────────────────


def scene_part(s: dict) -> str:
    out = ["<scene>", f"Scene: {s['title']} ({s['heading']}). {s['summary']}"]
    if s["purpose"]:
        out.append(f"What it is for: {s['purpose']}")
    out.append(f"Place: {s['place'] or '(see heading)'}; {'exterior' if s['exterior'] else 'interior'}. "
               f"Mood: {', '.join(s['mood']) or 'not stated'}.")
    out.append("People:")
    for p in s["people"]:
        feel = f"; feels {p['start']} -> {p['end']}" if p["start"] else ""
        out.append(f"- {p['name']} ({p['presence']}){': wants ' + p['wants'] if p['wants'] else ''}{feel}")
    if s["direction"]:
        out.append("The production's direction (the person's own style rules; each applies to its scope):")
        out += [f"- {d}" for d in s["direction"]]
    out.append("Script, in order:")
    for b in s["script"]:
        if b["kind"] == "dialogue":
            to = f" to {b['to']}" if b["to"] else ""
            via = f" (through the {b['through']})" if b["through"] else ""
            out.append(f"{b['n']} {b['who']}{via}{to}: \"{b['text'].strip()}\""
                       + (f" | how: {b['delivery']}" if b["delivery"] else "")
                       + (f" | intent: {b['intent']}" if b["intent"] else ""))
        else:
            out.append(f"action: {b['text']}" + (f" | intent: {b['intent']}" if b["intent"] else ""))
    out.append("</scene>")
    return NL.join(out)


def clip_ideas(s: dict, c: dict) -> list[tuple[str, str]]:
    query = f"{c['why']} {c['summary']} {' '.join(s['mood'])}"
    tags = []
    if c["speaks"]:
        tags.append("dialogue")
    if re.search(r"\b(walk|walks|runs?|running|chase|flees?|climbs?|arriv\w*|leaves|drives?)\b", query, re.I):
        tags.append("action")
    if re.search(r"\b(find|finds|found|discover\w*|reveal\w*|sees?|notic\w*|empty)\b", query, re.I):
        tags.append("reveal")
    wide_ok = s["exterior"] and c["role"] in ("master", "establishing", "clean_exit")
    aerial = {m for m in MOVES if m.startswith("aerial")} | {"flyover", "top_down"}
    fit = [m for m in MOVES if not (c["speaks"] and m in FAST_ON_FACE) and (m not in aerial or wide_ok)
           and LONG.get(m, 0) <= c["take_s"]]
    return kb.ideas(query, tags, fit)


IDEAS: dict[str, list[str]] = {}


def clips_part(s: dict) -> str:
    out = ["<clips>", "In cut order. SIZE is the size the clip OPENS on (fixed)."]
    for i, c in enumerate(s["clips"]):
        out.append(f"<clip slate=\"{c['slate']}\" n=\"{i + 1}\">")
        out.append(f"Setup {c['setup']}; role {c['role']}; SIZE {c['size']}; take {c['take_s']:g} s, handles "
                   f"{c['h_in']:g} s in / {c['h_out']:g} s out; sound {c['sound']}.")
        out.append(f"Planner's camera words (a hint): technique {c['technique']}; {c['rig']}; angle {c['angle']}; "
                   f"movement: {c['movement']}; lens {c['lens']}.")
        out.append(f"Why the planner made it: {c['why']}")
        out.append(f"What happens: {c['summary']}")
        for sub in c["subjects"]:
            out.append(f"In frame: {sub['desc']} Where: {sub['where']} Does: {sub['does']}")
        for h in c["heard"]:
            out.append(f"Only heard, never seen: {h}")
        if not c["subjects"]:
            out.append("No person in frame.")
        if c["opening"]:
            out.append(f"Opening picture: {c['opening']}")
        if c["beats"]:
            out.append("Beats: " + " | ".join(f"{b['time']}: {b['action']}" for b in c["beats"]))
        out.append("Spoken here: " + "; ".join(f"{sp['id']} {sp['who']} (~{sp['secs']} s)" for sp in c["spoken"])
                   if c["spoken"] else "Nobody speaks on camera in this clip.")
        offered = clip_ideas(s, c)
        IDEAS[c["slate"]] = [m for m, _ in offered]
        if offered:
            out.append("Ideas from the knowledge base (ideas, not orders): "
                       + " | ".join(f"{m}: {w}" for m, w in offered))
        out.append("</clip>")
    out.append("</clips>")
    return NL.join(out)


def brief(s: dict) -> str:
    omni = (HERE / "omni.md").read_text(encoding="utf-8").strip()
    return f"{scene_part(s)}\n\n{kb.menu(MOVES)}\n\n{clips_part(s)}\n\n{omni}"


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────────


def strength(c: ClipCamera) -> float:
    base = STRENGTH.get(c.move, 1) * SPEED_X.get(c.speed, 1)
    if c.angle not in ("eye_level",):
        base += 0.4 if c.angle in ("slightly_low", "slightly_high") else 0.8
    if c.support == "handheld_urgent":
        base += 0.8
    return round(base, 2)


def check_clip(c: ClipCamera, clip: dict) -> tuple[list[str], list[str]]:
    f: list[str] = []
    n: list[str] = []
    s = c.slate
    take = clip["take_s"]
    moving = c.move not in STILL | FLOATS
    if not 1 <= c.intensity <= 5:
        f.append(f"{s}: intensity {c.intensity} is not 1-5")
    if moving and c.move != "reframe":
        if not (0 <= c.start_s < c.end_s <= take + 1e-6):
            f.append(f"{s}: the move runs {c.start_s}-{c.end_s} s, outside a {take:g} s take")
        if LONG.get(c.move) and c.end_s - c.start_s < LONG[c.move]:
            f.append(f"{s}: {c.move} needs at least {LONG[c.move]:g} s")
        if c.speed == "none":
            f.append(f"{s}: {c.move} with speed none")
    if clip["speaks"] and (c.move in FAST_ON_FACE or c.speed in ("fast", "snap") or c.support == "handheld_urgent"):
        f.append(f"{s}: a face speaks here; {c.move}/{c.speed}/{c.support} breaks lip-sync")
    if clip["speaks"] and c.time != "normal":
        f.append(f"{s}: {c.time} with a spoken line")
    bold = c.move in BOLD or c.angle == "dutch" or c.support == "handheld_urgent"
    if bold and c.intensity < 4:
        f.append(f"{s}: a bold choice ({c.move}/{c.angle}/{c.support}) at intensity {c.intensity}: only at 4-5")
    size = clip["size"]
    if size in TIGHT and c.end_size in TIGHT:
        a, b = TIGHT[size], TIGHT[c.end_size]
        if (c.move in TIGHTER and b < a) or (c.move in WIDER and b > a):
            f.append(f"{s}: {c.move} from {size} cannot land on {c.end_size}")
    if c.angle != "eye_level" and not c.angle_reason.strip():
        f.append(f"{s}: angle {c.angle} with no angle_reason")
    sent = c.camera_sentence
    if (g := GEAR.search(sent)):
        f.append(f"{s}: the sentence names gear ('{g.group(0)}')")
    if LINE_ID.search(sent) or SINHALA.search(sent):
        f.append(f"{s}: the sentence has a line id or Sinhala")
    if (w := EDIT_WORDS.search(sent)):
        f.append(f"{s}: the sentence uses an edit/clock word ('{w.group(0)}')")
    if (w := TIMID.search(sent)):
        f.append(f"{s}: '{w.group(0)}' reads as no movement")
    if len(sent) > 220:
        f.append(f"{s}: the sentence is {len(sent)} characters (max 220)")
    if moving and (w := STILL_WORDS.search(sent)):
        f.append(f"{s}: the camera moves ({c.move}) but the sentence says '{w.group(0)}'")
    if moving and not MOVE_WORDS.search(sent):
        f.append(f"{s}: the camera moves ({c.move}) but the sentence has no move in it")
    if moving and not SUBJECT.search(sent):  # §6.3: "push closer as Dinu's palm meets the cart" read as Dinu pushing
        f.append(f"{s}: the sentence must have \"the camera\" as its subject")
    if c.focus == "rack_focus" and not (c.rack_from and c.rack_to and 0 < c.rack_at_s < take):
        f.append(f"{s}: rack focus without from/to/time inside the take")
    if c.move in FLOATS:
        n.append(f"{s}: {c.move} renders still (measured)")
    return f, n


def locked_direction(s: dict) -> bool:
    return any(re.search(r"locked[- ]off", d, re.I) for d in s["direction"])


def check_scene(a: SceneCamera, s: dict) -> tuple[list[str], list[str]]:
    faults: list[str] = []
    notes: list[str] = []
    want = [c["slate"] for c in s["clips"]]
    got = [c.slate for c in a.clips]
    if got != want:
        faults.append(f"answer slates {got} != the clips in order {want}")
    by = {c.slate: c for c in a.clips}
    for clip in s["clips"]:
        c = by.get(clip["slate"])
        if c:
            f, n = check_clip(c, clip)
            faults += f
            notes += n
    n_ = len(a.clips) or 1
    still = sum(1 for c in a.clips if c.move in STILL | FLOATS)
    if still > max(1, n_ // 4):
        (notes if locked_direction(s) else faults).append(
            f"scene: {still} of {n_} clips hold or float (render still); at most {max(1, n_ // 4)}"
            + (" (the production asks for locked-off frames in places: advisory)" if locked_direction(s) else ""))
    families = Counter(FAMILY.get(c.move, c.move) for c in a.clips if c.move not in STILL | FLOATS)
    for m, k in families.items():  # §6.4: by family, not by move name
        if n_ > 6 and k * 3 > n_ + 2:
            faults.append(f"scene: the {m} family on {k} of {n_} clips; vary the ways the camera moves")
    if n_ >= 10 and set(families) <= {"forward"} and any(c.intensity >= 3 for c in a.clips):
        notes.append("scene: every move goes forward; one non-forward family where the action offers motion")
    # the peak gets the strongest camera
    peak = by.get(a.peak_slate)
    if peak is None:
        faults.append(f"scene: peak_slate {a.peak_slate} is not a clip")
    else:
        top = max(c.intensity for c in a.clips)
        if peak.intensity < top:
            faults.append(f"scene: the peak {a.peak_slate} has intensity {peak.intensity}, another clip has {top}")
        stronger = [c.slate for c in a.clips if c.intensity < peak.intensity and strength(c) > strength(peak) + 1.0]
        if stronger and not (peak.move == "hold" and peak.moment in ("realisation", "tension")):
            faults.append(f"scene: calmer clips {stronger} have a stronger camera than the peak {a.peak_slate} "
                          f"({strength(peak)})")
    # angle and height
    eye = all(c.angle == "eye_level" and c.height in ("eye", "shoulder", "chest") for c in a.clips)
    turn = any(c.intensity >= 4 for c in a.clips) or any(c.power not in ("equal", "none", "") for c in a.clips)
    if n_ >= 6 and turn and eye:
        faults.append("scene: a turn or a power shift, but every clip is eye level at eye height")
    level = sum(1 for c in a.clips if c.angle == "eye_level" and c.height in ("eye", "shoulder", "chest"))
    if n_ >= 6 and turn and not eye and level * 3 > n_ * 2:  # §6.2 + plan/2026-11-20c deviation 5: a share
        (notes if locked_direction(s) else faults).append(
            f"scene: {level} of {n_} clips at eye level with a turn or a power shift; at most two in three")
    setups: dict[str, set[tuple[str, str]]] = {}
    for clip in s["clips"]:
        c = by.get(clip["slate"])
        if c and c.move not in ANGLE_MOVES:
            setups.setdefault(clip["setup"], set()).add((c.angle, c.height))
    for letter, ah in setups.items():
        if len(ah) > 1:
            notes.append(f"setup {letter}: angle/height differ across its clips {sorted(ah)}")
    return faults, notes


# ── the model ────────────────────────────────────────────────────────────────────────────────────────────────────────


def env(key: str) -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit(f"{key} is not set in .env")


def dollars(u: dict[str, int]) -> float:
    return ((u["input"] - u["cached"]) * PRICE["in"] + u["cached"] * PRICE["cached"] + u["output"] * PRICE["out"]) / 1e6


def ask(client: Any, messages: list[dict[str, str]]) -> tuple[SceneCamera, dict[str, int], str, float]:
    started = time.monotonic()
    resp = client.responses.parse(model=MODEL, reasoning={"effort": EFFORT}, input=messages, text_format=SceneCamera,
                                  max_output_tokens=MAX_OUT)
    u = resp.usage
    usage = {"input": u.input_tokens, "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "output": u.output_tokens,
             "reasoning": getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0}
    return resp.output_parsed, usage, resp.output_text, round(time.monotonic() - started, 1)


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def report(out: Path, a: SceneCamera, s: dict, faults: list[str], notes: list[str], meta: dict) -> None:
    by = {c.slate: c for c in a.clips}
    fam = Counter(c.move for c in a.clips)
    angles = Counter(f"{c.angle}/{c.height}" for c in a.clips)
    real = sum(1 for c in a.clips if c.move not in STILL | FLOATS)
    md = [f"# Camera moves: {s['sid']}: {s['title']}", "",
          f"{MODEL} ({EFFORT}); {meta['calls']} call(s); ${meta['usd']:.4f}; {meta['seconds']} s.", "",
          f"**Camera language:** {a.camera_language}", "", f"**Arc:** {a.arc}", "",
          f"**Peak:** {a.peak_slate}", "",
          f"Real moves {real} of {len(a.clips)}; moves: " + ", ".join(f"{k} x{v}" for k, v in fam.most_common()), "",
          "Angle/height: " + ", ".join(f"{k} x{v}" for k, v in angles.most_common()), "",
          f"## Checks: {len(faults)} fault(s) left, {len(meta['first_faults'])} on the first answer", ""]
    md += [f"- FAULT {x}" for x in faults] or ["- none left"]
    if meta["first_faults"]:
        md += ["", "First answer's faults (sent back once):"] + [f"- {x}" for x in meta["first_faults"]]
    md += ["", "Advisories:"] + ([f"- {x}" for x in notes] or ["- none"]) + ["", "## Clip by clip", ""]
    md += ["| clip | size | take | moment / int / power | move | speed | angle / height | strength | why |",
           "|---|---|---|---|---|---|---|---|---|"]
    for clip in s["clips"]:
        c = by.get(clip["slate"])
        if not c:
            continue
        md.append(f"| {c.slate} | {clip['size']}->{c.end_size} | {clip['take_s']:g}s{' 🗣' if clip['speaks'] else ''} "
                  f"| {c.moment} {c.intensity} / {c.power} | **{c.move}** | {c.speed} | {c.angle} / {c.height} | "
                  f"{strength(c)} | {c.why} |")
    md += ["", "## Camera sentences", ""]
    for clip in s["clips"]:
        c = by.get(clip["slate"])
        if c:
            today = s["camera_line"].get(c.slate) or f"(planner: {clip['technique']}; {clip['movement']})"
            md.append(f"- **{c.slate}** ({c.support}): \"{c.camera_sentence}\"  "
                      f"_angle: {c.angle_reason or '-'}_  _today: {today[:160]}_")
    (out / "report.md").write_text(NL.join(md), encoding="utf-8")


def coverage() -> None:
    runs = sorted(p for p in (HERE / "runs").iterdir() if (p / "answer.json").exists())
    used = {r.name: Counter(c["move"] for c in json.loads((r / "answer.json").read_text(encoding="utf-8"))["answer"]
                            ["clips"]) for r in runs}
    ang = {r.name: Counter(c["angle"] for c in json.loads((r / "answer.json").read_text(encoding="utf-8"))["answer"]
                           ["clips"]) for r in runs}
    md = ["# Moves and angles used across the camera_moves runs", "", "| Move | " + " | ".join(used) + " |",
          "|---|" + "---|" * len(used)]
    for m in MOVES:
        if any(u.get(m) for u in used.values()):
            md.append(f"| {m} | " + " | ".join(str(u.get(m, "")) for u in used.values()) + " |")
    never = [m for m in MOVES if not any(u.get(m) for u in used.values())]
    md += ["", f"Moves used: {len(MOVES) - len(never)} of {len(MOVES)}. Never: {', '.join(never)}", "",
           "| Angle | " + " | ".join(ang) + " |", "|---|" + "---|" * len(ang)]
    for g in get_args(Angle):
        if any(u.get(g) for u in ang.values()):
            md.append(f"| {g} | " + " | ".join(str(u.get(g, "")) for u in ang.values()) + " |")
    (HERE / "runs" / "coverage.md").write_text(NL.join(md), encoding="utf-8")
    print(f"coverage: {len(MOVES) - len(never)} of {len(MOVES)} moves used over {len(runs)} runs")


def main() -> int:
    from hiru_ai.core.tokens import tokens_of

    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()
    if args.coverage:
        coverage()
        return 0
    s = sources.load(args.scene)
    out = HERE / "runs" / args.scene
    out.mkdir(parents=True, exist_ok=True)
    system = (HERE / "system.md").read_text(encoding="utf-8")
    text = brief(s)
    (out / "brief.txt").write_text(f"{system}\n\n=== user ===\n{text}", encoding="utf-8")
    tok = tokens_of(system) + tokens_of(text)
    print(f"{args.scene}: {s['title']}; {len(s['clips'])} clips; ~{tok} tokens in")
    if not args.yes:
        return 0
    if (out / "answer.json").exists():
        print("already answered")
        return 0
    wallet = Wallet("openai")
    worst = (tok * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6
    if not wallet.allow_usd(worst, f"{args.scene} scene"):
        return 1
    from openai import OpenAI

    client = OpenAI(api_key=env("OPENAI__API_KEY"))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": text}]
    a, usage, raw, secs = ask(client, messages)
    usd = dollars(usage)
    wallet.add_usd(f"{args.scene} scene", usd, usage)
    calls, seconds = 1, secs
    faults, notes = check_scene(a, s)
    first = list(faults)
    print(f"  answer: ${usd:.4f}, {secs} s, {len(faults)} fault(s), usage {usage}")
    if faults and wallet.allow_usd(((tok + tokens_of(raw)) * PRICE["in"] + MAX_OUT * PRICE["out"]) / 1e6,
                                   f"{args.scene} repair"):
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Code checked your answer and found:\n- " + "\n- ".join(faults)
                      + "\nAnswer again, complete (every clip), with these fixed and everything else kept."}]
        a, usage, raw, secs = ask(client, messages)
        u2 = dollars(usage)
        usd += u2
        wallet.add_usd(f"{args.scene} repair", u2, usage)
        calls, seconds = 2, seconds + secs
        faults, notes = check_scene(a, s)
        print(f"  repair: {secs} s, {len(faults)} fault(s) left")
    (out / "answer.json").write_text(json.dumps(
        {"answer": a.model_dump(), "first_faults": first, "faults": faults, "notes": notes, "calls": calls,
         "seconds": seconds, "usd": round(usd, 5), "ideas": IDEAS}, indent=1, ensure_ascii=False), encoding="utf-8")
    report(out, a, s, faults, notes, {"calls": calls, "usd": usd, "seconds": seconds, "first_faults": first})
    coverage()
    print(f"spent ${usd:.4f}; lab total ${wallet.data['usd']:.4f}; report {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
