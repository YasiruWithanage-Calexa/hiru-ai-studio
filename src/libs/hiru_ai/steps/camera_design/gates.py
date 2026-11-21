"""The checks every Camera agent answer passes (plan/2026-11-20c D9), ported from `lab/camera_agent/run.py`
(`check_clip`, `check_scene`), which proved them on Api Denna E01; plus the cinematic checks of
`lab/camera_moves/run.py` (plan/2026-11-20d §6, proven on seven dramatic scenes and the person's own): intensity 1-5, a
bold choice only at 4-5, a reason for every angle off eye level, "the camera" as the sentence's subject, variety by
move FAMILY, the peak gets the strongest camera, and at most two clips in three at eye level in a scene with a turn or
a power shift.

    check_clip(c, clip)              -> (faults, notes) for one clip's design
    check_scene(answer, clips, ...)  -> (faults, notes) for a scene's answer (or a one-shot answer: `focus`)

A fault gets the answer ONE repair call; a clip still faulty after it keeps the rule recommendation (D10). A note is
an advisory for the job's log. `c` is a `ClipCamera` as data; `clip` is what `facts.clip_facts` built.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from contracts import camera as cam

Row = dict[str, Any]

GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|stabili[sz]er|rig|drone|tracks?\b(?! (?:"
                  r"her|him|them|the))|rails?|camera operator|operator)\b", re.I)
STILL_WORDS = re.compile(r"\b(unmoving|locked[- ]off|static|motionless|perfectly still|fixed frame)\b", re.I)
MOVE_WORDS = re.compile(r"\b(push(?:es|ing)?|pull(?:s|ing)?|eases?|easing|creep(?:s|ing)?|drift(?:s|ing)?"
                        r"|float(?:s|ing)?|breath(?:e|es|ing)?|sway(?:s|ing)?|track(?:s|ing)?|follow(?:s|ing)?|leads?|leading|arc(?:s|ing)?"
                        r"|circl(?:e|es|ing)|orbit(?:s|ing)?|pan(?:s|ning)?|tilt(?:s|ing)?|ris(?:e|es|ing)|lower(?:s|ing)?"
                        r"|descend(?:s|ing)?|glid(?:e|es|ing)|mov(?:e|es|ing)|zoom(?:s|ing)?|whip(?:s|ping)?|handheld"
                        r"|closer|back(?:s)? away|slides?|sliding|reframes?|reframing|shak(?:e|es|ing)|swings?|travels?"
                        r"|crash(?:es)?|snaps?|flies|rolls?)\b", re.I)
TIMID = re.compile(r"\b(imperceptib\w*|barely|minute(?:ly)?|almost still|nearly still|tiny|minimal(?:ly)?)\b", re.I)
NOT_CAMERA = re.compile(r"\b(exclud\w*|no (?:people|one|person)|readable|lips? (?:clear|visible)|keep(?:ing)? "
                        r"(?:the|her|his|their) (?:face|lips|screen|hands?|phone)|visible throughout)\b", re.I)
EDIT_WORDS = re.compile(r"\b(handles?|tail|before the cut|the cut|in the edit|take|\d+(?:\.\d+)? seconds?|"
                        r"(?:one|two|three|four|five|six|seven|eight) seconds?|middle seconds?)\b", re.I)
LINE_ID = re.compile(r"\bL\d+\b")
SINHALA = re.compile(r"[඀-෿]")
MAX_SENTENCE = 220  # lab/camera_moves
SUBJECT = re.compile(r"\bthe camera\b", re.I)  # §6.3: "push closer as Dinu's palm meets the cart" read as Dinu pushing
# lab/camera_moves: how strong a camera choice reads on screen (move family), times the speed
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
LEVEL_HEIGHTS = ("eye", "shoulder", "chest")


def _intensity(c: Mapping[str, Any]) -> int:
    try:
        return int(c.get("intensity") or 0)
    except (TypeError, ValueError):
        return 0


def strength(c: Mapping[str, Any]) -> float:
    """How strong a clip's camera reads (lab/camera_moves `strength`)."""
    base = STRENGTH.get(str(c.get("move")), 1) * SPEED_X.get(str(c.get("speed")), 1)
    angle = str(c.get("angle") or "eye_level")
    if angle != "eye_level":
        base += 0.4 if angle in ("slightly_low", "slightly_high") else 0.8
    if c.get("support") == "handheld_urgent":
        base += 0.8
    return round(base, 2)


def _f(c: Mapping[str, Any], key: str) -> float:
    try:
        return float(c.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def check_clip(c: Mapping[str, Any], clip: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(faults that must be fixed, advisories)."""
    faults: list[str] = []
    notes: list[str] = []
    s = str(c.get("slate") or clip.get("slate"))
    take = float(clip.get("take_s") or 0)
    size = str(clip.get("size") or "")
    speaks = bool(clip.get("speaks"))
    move, speed, support = str(c.get("move")), str(c.get("speed")), str(c.get("support"))
    start, end = _f(c, "start_s"), _f(c, "end_s")
    moving = move not in cam.STILL_MOVES
    if move == "hold" and support not in ("locked_off", "operated", "pov"):
        notes.append(f"{s}: a hold on {support}")
    if moving and move not in cam.FLOATS:
        if not (0 <= start < end <= take + 1e-6):
            faults.append(f"{s}: the move runs {start:g}-{end:g} s, outside a {take:g} s take")
        need = cam.LONG_MOVES.get(move)
        if need and end - start < need:
            faults.append(f"{s}: {move} needs at least {need:g} s, it has {end - start:g} s")
        if speed == "none":
            faults.append(f"{s}: {move} with speed none")
        if not str(c.get("trigger") or "").strip():
            faults.append(f"{s}: {move} has no trigger")
    if speaks and (move in cam.FAST_MOVES or speed in ("fast", "snap") or support == "handheld_urgent"):
        faults.append(f"{s}: a face speaks here; {move}/{speed}/{support} breaks lip-sync")
    if speaks and str(c.get("time") or "normal") != "normal":
        faults.append(f"{s}: {c.get('time')} with a spoken line")
    intensity = _intensity(c)
    if not 1 <= intensity <= 5:
        faults.append(f"{s}: intensity {c.get('intensity')} is not 1-5")
    angle = str(c.get("angle") or "eye_level")
    bold = move in BOLD or angle == "dutch" or support == "handheld_urgent"
    if bold and intensity < 4:
        faults.append(f"{s}: a bold choice ({move}/{angle}/{support}) at intensity {intensity}: only at 4-5")
    if angle != "eye_level" and not str(c.get("angle_reason") or "").strip():
        faults.append(f"{s}: angle {angle} with no angle_reason")
    end_size = str(c.get("end_size") or "")
    if size in cam.TIGHT and end_size in cam.TIGHT:
        a, b = cam.TIGHT[size], cam.TIGHT[end_size]
        if (move in cam.TIGHTER and b < a) or (move in cam.WIDER and b > a):
            faults.append(f"{s}: {move} from {size} cannot land on {end_size}")
        if move not in cam.TIGHTER | cam.WIDER and abs(b - a) > 1:
            faults.append(f"{s}: {move} keeps the size, but it lands on {end_size} from {size}")
    sent = str(c.get("camera_sentence") or "")
    if (g := GEAR.search(sent)):
        faults.append(f"{s}: the camera sentence names gear ('{g.group(0)}'), the video model draws it")
    if LINE_ID.search(sent) or SINHALA.search(sent):
        faults.append(f"{s}: the camera sentence has a line id or Sinhala")
    if (w := EDIT_WORDS.search(sent)):
        faults.append(f"{s}: the camera sentence uses an edit/clock word ('{w.group(0)}') the video model does not "
                      f"know; say it by what happens on screen")
    if len(sent) > MAX_SENTENCE:
        faults.append(f"{s}: the camera sentence is {len(sent)} characters (max {MAX_SENTENCE})")
    if not sent.strip():
        faults.append(f"{s}: no camera sentence")
    if (w := TIMID.search(f"{sent} {c.get('direction') or ''}")):
        faults.append(f"{s}: '{w.group(0)}' reads as no movement to the video model; make the motion visible")
    if (w := NOT_CAMERA.search(sent)):
        faults.append(f"{s}: the camera sentence carries a picture rule ('{w.group(0)}'); camera only")
    if clip.get("lens") and c.get("lens") and str(c["lens"]) not in str(clip["lens"]):
        notes.append(f"{s}: lens {clip.get('lens')} -> {c.get('lens')} (the first frame follows)")
    if moving and (w := STILL_WORDS.search(sent)):
        faults.append(f"{s}: the camera moves ({move}) but the sentence says '{w.group(0)}'")
    if moving and not MOVE_WORDS.search(sent):
        faults.append(f"{s}: the camera moves ({move}) but the sentence has no move in it")
    if moving and not SUBJECT.search(sent):  # §6.3: the model reads a subject-less move as the person's action
        faults.append(f"{s}: the sentence must have \"the camera\" as its subject")
    if not moving and support == "locked_off" and (w := MOVE_WORDS.search(sent)) and not STILL_WORDS.search(sent):
        faults.append(f"{s}: a locked-off hold, but the sentence says '{w.group(0)}'")
    if move in cam.RISKY and c.get("omni") != "risky":
        notes.append(f"{s}: {move} is on the risky list but marked works")
    racked = c.get("rack_from") and c.get("rack_to") and 0 < _f(c, "rack_at_s") < take
    if c.get("focus") == "rack_focus" and not racked:
        faults.append(f"{s}: rack focus without from/to/time inside the take")
    return faults, notes


def check_scene(answer: Mapping[str, Any], clips: Sequence[Mapping[str, Any]], *,
                focus: Sequence[str] = (), locked: bool = False) -> tuple[list[str], list[str]]:
    """A scene's answer (every clip, in order), or a one-shot answer (`focus`: the slates asked for, in order). The
    scene-wide shares are counted over the scene as it would stand: the answer's clips over the rest's `current`.
    `locked`: the production's own direction asks for locked-off frames somewhere (the hold and eye-level shares are
    then advisories, lab/camera_moves `locked_direction`)."""
    faults: list[str] = []
    notes: list[str] = []
    got_clips = [c for c in answer.get("clips") or [] if isinstance(c, Mapping)]
    want = list(focus) or [str(c["slate"]) for c in clips]
    got = [str(c.get("slate")) for c in got_clips]
    if got != want:
        faults.append(f"answer slates {got} != the clips asked for, in order {want}")
    by_slate = {str(c["slate"]): c for c in clips}
    by = {str(c.get("slate")): c for c in got_clips}
    for slate in want:
        c = by.get(slate)
        if c is not None and slate in by_slate:
            clip_faults, clip_notes = check_clip(c, by_slate[slate])
            faults += clip_faults
            notes += clip_notes
    # the scene as it would stand: the answer where it answered, else the clip's current design
    scene = [by.get(str(c["slate"])) or c.get("current") or {} for c in clips]
    scene = [s for s in scene if s.get("move")]
    setups: dict[str, set[str]] = {}
    for clip in clips:
        c = by.get(str(clip["slate"]))
        if c is not None:
            setups.setdefault(str(clip.get("setup") or ""), set()).add(str(c.get("support")))
    for letter, sup in setups.items():
        if letter and len(sup) > 1:
            notes.append(f"setup {letter}: supports differ across its clips ({', '.join(sorted(sup))})")
    n = len(scene)
    if not n:
        return faults, notes
    # one-shot mode cannot redesign the rest of the scene: its shares are advisories there
    wide = notes if focus else faults
    soft = notes if (focus or locked) else faults  # one-shot, or the production's locked-off direction: advisories
    still = sum(1 for c in scene if c.get("move") in cam.HOLDS)  # measured: floats render still
    if still > max(1, n // 4):
        soft.append(f"scene: {still} of {n} clips are holds or floats, which render still (at most {max(1, n // 4)})"
                    + (" (the production asks for locked-off frames in places: advisory)" if locked else ""))
    families = Counter(FAMILY.get(str(c.get("move")), str(c.get("move"))) for c in scene
                       if c.get("move") not in cam.HOLDS)
    for m, k in families.items():  # §6.4: by family, not by move name
        if n > 6 and k * 3 > n + 2:
            wide.append(f"scene: the {m} family on {k} of {n} clips; vary the ways the camera moves")
    if n >= 10 and set(families) <= {"forward"} and any(_intensity(c) >= 3 for c in scene):
        notes.append("scene: every move goes forward; one non-forward family where the action offers motion")
    # the peak gets the strongest camera (a scene answer only: a one-shot answer cannot move the peak)
    if not focus:
        peak = by.get(str(answer.get("peak_slate") or ""))
        if peak is None:
            faults.append(f"scene: peak_slate {answer.get('peak_slate')} is not a clip")
        else:
            top = max(_intensity(c) for c in got_clips) if got_clips else 0
            if _intensity(peak) < top:
                faults.append(f"scene: the peak {answer.get('peak_slate')} has intensity {_intensity(peak)}, another "
                              f"clip has {top}")
            stronger = [str(c.get("slate")) for c in got_clips
                        if _intensity(c) < _intensity(peak) and strength(c) > strength(peak) + 1.0]
            if stronger and not (peak.get("move") == "hold" and peak.get("moment") in ("realisation", "tension")):
                faults.append(f"scene: calmer clips {stronger} have a stronger camera than the peak "
                              f"{answer.get('peak_slate')} ({strength(peak)})")
    # angle and height carry power (§6.2): a turn or a power shift is not shot all at eye level
    level = sum(1 for c in scene if (c.get("angle") or "eye_level") == "eye_level"
                and (c.get("height") or "eye") in LEVEL_HEIGHTS)
    turn = any(_intensity(c) >= 4 for c in scene) or any(
        str(c.get("power") or "").strip().lower() not in ("equal", "none", "") for c in scene)
    if n >= 6 and turn and level == n:
        soft.append("scene: a turn or a power shift, but every clip is eye level at eye height")
    elif n >= 6 and turn and level * 3 > n * 2:  # §6.2 + plan/2026-11-20c deviation 5: a share
        soft.append(f"scene: {level} of {n} clips at eye level with a turn or a power shift; at most two in three")
    seq = [str(c.get("move")) for c in scene]
    for i in range(len(seq) - 2):
        if seq[i] == seq[i + 1] == seq[i + 2] and seq[i] not in cam.STILL_MOVES:
            notes.append(f"{scene[i].get('slate')}-{scene[i + 2].get('slate')}: {seq[i]} three clips in a row")
    axes = Counter(str(c.get("axis")) for c in scene if c.get("axis") and c.get("axis") != "crossing_on_screen")
    if len(axes) > 1:
        notes.append(f"axis changes in the scene without a crossing on screen: {dict(axes)}")
    return faults, notes


def faulty_slates(faults: Sequence[str], slates: Sequence[str]) -> set[str]:
    """The clips a list of faults names (by its "slate: ..." head). A scene-wide fault names none."""
    named = {f.split(":", 1)[0].strip() for f in faults}
    return {s for s in slates if s in named}
