"""The camera catalogue as data (plan/2026-11-20c D6, D7): every move, support, speed, size, angle, height, lens, stop,
focus, composition, time and axis the Camera agent may choose, with the panel's words for each, the knowledge-base term
behind each move, its family, its least length, whether it is fast, and what the video model (Omni 1.2) does with it.

ONE list for the agent's schema, the panel (`contracts.producer.CAMERA_OPTIONS` is built from it, and the interface's
`camera-options.ts` mirrors it), the gates (`hiru_ai.steps.camera_design.gates`) and the prompt words
(`contracts.camera_words`). Ported from `lab/camera_agent/run.py` (the Literals, FAST/LONG/RISKY/TIGHT) and `kb.py`
(MOVE_TERM, FOCUS_TERM, OWN, VARIANT), which the lab proved on Api Denna E01.

The agent speaks SLUGS (`push_in`), the panel LABELS ("Push in"). Stored designs and a person's overrides written
before this plan used five moves ("Static", "Dolly in", "Dolly out", "Pan", "Handheld"): `normalise` maps them, so
they still validate (`OLD`).

Pure standard library (the `contracts` rule).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ── moves ──────────────────────────────────────────────────────────────────────────────────────────────────────────

Family = Literal["still", "forward", "back", "lateral", "around", "rotate", "vertical", "lens", "aerial", "transition"]
# What the video model does with a move (D7). measured_works / measured_still: rendered on Omni 1.2 Flash, 2026-11-20
# (lab/camera_agent renders); provisional: not measured yet; risky: may be ignored or warp faces.
OmniStatus = Literal["measured_works", "measured_still", "provisional", "risky"]


@dataclass(frozen=True)
class Move:
    slug: str
    label: str
    family: Family
    term: str  # the cinematography knowledge base's term slug ("" = not in the base: `OWN` says what it does)
    omni: OmniStatus
    min_s: float = 0.0  # the least time the move needs in a take
    fast: bool = False  # breaks lip-sync on a speaking face
    words: str = ""  # what the camera does, for a prompt: "pushes in" (`contracts.camera_words`)


MOVES: tuple[Move, ...] = (
    Move("hold", "Hold", "still", "static_locked_off_shot", "measured_works", words="holds still"),
    Move("breathing", "Breathing", "still", "", "measured_still", words="breathes gently, held by hand"),
    Move("drift", "Drift", "still", "", "measured_still", words="drifts slowly"),
    Move("reframe", "Reframe", "still", "", "provisional", words="reframes gently as they shift"),
    Move("push_in", "Push in", "forward", "dolly", "measured_works", words="pushes in"),
    Move("slow_creep", "Slow creep", "forward", "push_in_creep_in", "measured_works", words="creeps closer"),
    Move("pull_out", "Pull out", "back", "pull_out", "measured_works", words="pulls back"),
    Move("push_then_hold", "Push, then hold", "forward", "", "measured_works", words="pushes in, then comes to rest"),
    Move("pull_back_reveal", "Pull-back reveal", "back", "reveal_shot", "provisional",
         words="pulls back to reveal the space"),
    Move("push_past_foreground", "Push past foreground", "forward", "", "risky",
         words="moves forward past the foreground"),
    Move("truck_left", "Truck left", "lateral", "truck", "provisional", words="moves sideways to the left"),
    Move("truck_right", "Truck right", "lateral", "truck", "provisional", words="moves sideways to the right"),
    Move("tracking_alongside", "Track alongside", "lateral", "crab_shot", "provisional", words="tracks alongside"),
    Move("lead", "Lead", "lateral", "tracking_shot", "provisional", words="moves backward ahead of them"),
    Move("follow", "Follow", "lateral", "tracking_shot", "provisional", words="follows behind"),
    Move("track_then_hold", "Track, then hold", "lateral", "", "provisional",
         words="travels with them, then comes to rest"),
    Move("arc_left", "Arc left", "around", "arc_shot", "provisional", min_s=3.0, words="arcs slowly to the left"),
    Move("arc_right", "Arc right", "around", "arc_shot", "measured_works", min_s=3.0, words="arcs slowly to the right"),
    Move("half_orbit", "Half orbit", "around", "orbit_shot", "risky", min_s=5.0, fast=True,
         words="circles halfway around"),
    Move("orbit", "Orbit", "around", "orbit_shot", "risky", min_s=8.0, fast=True, words="circles all the way around"),
    Move("circle_two", "Circle the two", "around", "circle_track_shot", "risky", min_s=6.0, fast=True,
         words="circles around both of them"),
    Move("pan_left", "Pan left", "rotate", "pan", "provisional", words="pans left"),
    Move("pan_right", "Pan right", "rotate", "pan", "provisional", words="pans right"),
    Move("follow_pan", "Follow pan", "rotate", "pan", "provisional", words="pans to follow"),
    Move("whip_pan", "Whip pan", "rotate", "whip_pan", "risky", fast=True, words="whips sideways"),
    Move("slow_pan_reveal", "Slow pan reveal", "rotate", "pan", "provisional", words="pans slowly to discover"),
    Move("tilt_up", "Tilt up", "rotate", "tilt", "provisional", words="tilts up"),
    Move("tilt_down", "Tilt down", "rotate", "tilt", "provisional", words="tilts down"),
    Move("tilt_reveal", "Tilt reveal", "rotate", "low_to_high_high_to_low_reveal", "provisional",
         words="tilts to reveal"),
    Move("dutch_roll", "Dutch roll", "rotate", "roll", "risky", words="rolls off level"),
    Move("pedestal_up", "Pedestal up", "vertical", "pedestal", "provisional", words="rises straight up"),
    Move("pedestal_down", "Pedestal down", "vertical", "pedestal", "provisional", words="lowers straight down"),
    Move("crane_up", "Crane up", "vertical", "boom_shot", "provisional", words="rises up and away"),
    Move("crane_down", "Crane down", "vertical", "boom_shot", "provisional", words="descends toward them"),
    Move("rising_reveal", "Rising reveal", "vertical", "boom_up_boom_down", "provisional",
         words="rises to reveal the place"),
    Move("zoom_in", "Zoom in", "lens", "zoom", "provisional", words="zooms in"),
    Move("zoom_out", "Zoom out", "lens", "zoom", "provisional", words="zooms out"),
    Move("slow_zoom", "Slow zoom", "lens", "zoom", "provisional", words="zooms in very slowly"),
    Move("snap_zoom", "Snap zoom", "lens", "zoom", "risky", fast=True, words="snaps in"),
    Move("crash_zoom", "Crash zoom", "lens", "zoom", "risky", fast=True, words="crashes in"),
    Move("dolly_zoom", "Dolly zoom", "lens", "dolly_zoom", "risky", fast=True,
         words="moves in while the background stretches away"),
    Move("aerial_establishing", "Aerial establishing", "aerial", "aerial_drone_shot", "provisional",
         words="glides high over the place"),
    Move("aerial_reveal", "Aerial reveal", "aerial", "aerial_drone_shot", "risky", min_s=4.0,
         words="rises high to reveal the place"),
    Move("aerial_pull_away", "Aerial pull away", "aerial", "aerial_drone_shot", "provisional",
         words="pulls away and up into the sky"),
    Move("top_down", "Top down", "aerial", "overhead_top_down_shot", "risky", words="looks straight down from above"),
    Move("flyover", "Flyover", "aerial", "aerial_drone_shot", "risky", min_s=4.0, fast=True,
         words="flies over the place"),
    Move("whip_out", "Whip out", "transition", "whip_pan", "risky", fast=True, words="whips away"),
    Move("whip_in", "Whip in", "transition", "whip_pan", "risky", fast=True, words="whips in"),
    Move("focus_out", "Focus out", "transition", "bokeh_transition", "risky", words="lets the focus go soft"),
    Move("focus_in", "Focus in", "transition", "bokeh_transition", "risky", words="brings the focus in from soft"),
    Move("shake", "Shake", "transition", "handheld", "risky", fast=True, words="shakes with the impact"),
)
MOVE: dict[str, Move] = {m.slug: m for m in MOVES}
MOVE_SLUGS: tuple[str, ...] = tuple(m.slug for m in MOVES)

# A float renders as a still frame on Omni (measured 2026-11-20): every check counts it as a hold.
STILL_MOVES = frozenset({"hold"})
FLOATS = frozenset({"breathing", "drift", "reframe"})
HOLDS = STILL_MOVES | FLOATS
FAST_MOVES = frozenset(m.slug for m in MOVES if m.fast)
LONG_MOVES: dict[str, float] = {m.slug: m.min_s for m in MOVES if m.min_s}
RISKY = frozenset(m.slug for m in MOVES if m.omni == "risky")
TIGHTER = frozenset({"push_in", "slow_creep", "push_then_hold", "zoom_in", "slow_zoom", "push_past_foreground",
                     "crash_zoom", "snap_zoom"})
WIDER = frozenset({"pull_out", "pull_back_reveal", "zoom_out", "aerial_pull_away", "crane_up", "rising_reveal"})
AERIAL = frozenset(m.slug for m in MOVES if m.family == "aerial")

# ── the other fields: slug -> the panel's label ─────────────────────────────────────────────────────────────────────

SUPPORTS: dict[str, str] = {
    "locked_off": "Locked off", "operated": "Operated", "handheld_subtle": "Handheld, calm",
    "handheld_urgent": "Handheld, urgent", "shoulder": "Shoulder", "steadicam": "Steadicam", "gimbal": "Gimbal",
    "dolly": "Dolly", "slider": "Slider", "jib": "Jib", "crane": "Crane", "drone": "Drone",
    "vehicle_mount": "Vehicle mount", "body_mount": "Body mount", "pov": "Point of view",
}
SPEEDS: dict[str, str] = {"none": "None", "very_slow": "Very slow", "slow": "Slow", "medium": "Medium",
                          "fast": "Fast", "snap": "Snap"}
# The planner's size codes (Raphael's wider list; `shots.framing` keeps its seven) -> the panel's label
SIZES: dict[str, str] = {
    "ECU": "Extreme close-up", "CU": "Close-up", "MCU": "Medium close-up", "MS": "Medium shot",
    "MWS": "Medium wide shot", "MLS": "Medium long shot", "WIDE": "Wide shot", "EWS": "Extreme wide shot",
    "TWO": "Two-shot", "OTS": "Over-the-shoulder", "INSERT": "Insert",
}
# How tight each size is: a push lands tighter, a pull wider, any other move keeps the size (one step either way)
TIGHT: dict[str, int] = {"EWS": 0, "WIDE": 1, "MLS": 2, "MWS": 2, "TWO": 3, "MS": 3, "OTS": 4, "MCU": 4, "CU": 5,
                         "INSERT": 5, "ECU": 6}
ANGLES: dict[str, str] = {
    "eye_level": "Eye level", "slightly_low": "Slightly low", "low": "Low angle", "slightly_high": "Slightly high",
    "high": "High angle", "overhead": "Overhead", "worms_eye": "Worm's-eye", "dutch": "Dutch",
}
HEIGHTS: dict[str, str] = {
    "ground": "Ground", "knee": "Knee height", "hip": "Hip height", "chest": "Chest height",
    "shoulder": "Shoulder height", "eye": "Eye height", "above_head": "Above head", "aerial": "Aerial",
}
LENSES: tuple[str, ...] = ("18mm", "24mm", "28mm", "32mm", "35mm", "40mm", "50mm", "55mm", "65mm", "75mm", "85mm",
                           "100mm", "135mm")
APERTURES: tuple[str, ...] = ("f/1.8", "f/2", "f/2.8", "f/4", "f/5.6", "f/8")
FOCUS: dict[str, str] = {"shallow_isolation": "Shallow, isolated", "medium": "Medium depth", "deep": "Deep focus",
                         "rack_focus": "Rack focus", "focus_follow": "Follow focus"}
COMPOSITIONS: dict[str, str] = {
    "rule_of_thirds": "Rule of thirds", "centred": "Centred", "foreground_framing": "Foreground framing",
    "negative_space": "Negative space", "frame_within_frame": "Frame within a frame",
    "over_shoulder": "Over the shoulder", "symmetric": "Symmetric", "lead_room": "Lead room",
}
TIMES: dict[str, str] = {"normal": "Normal", "slow_motion": "Slow motion", "timelapse": "Timelapse",
                         "hyperlapse": "Hyperlapse"}
AXES: dict[str, str] = {"side_a": "Side A · left to right", "side_b": "Side B · right to left",
                        "crossing_on_screen": "Crossing on screen"}
LIGHTING: tuple[str, ...] = ("Night, lamp key", "Night, moonlight", "Day, window light", "Day, open sun",
                             "Dawn, soft ambient", "Dusk, soft ambient")

# eye level at eye height: the connected run's every clip (§6.1); a scene of 6+ clips must vary it
EYE_LEVEL = ("eye_level", "eye")

# ── the old panel's words (before plan/2026-11-20c) ─────────────────────────────────────────────────────────────────

OLD: dict[str, dict[str, str]] = {
    "movement": {"Static": "Hold", "Dolly in": "Push in", "Dolly out": "Pull out", "Pan": "Pan right",
                 "Handheld": "Hold"},
}
# An old "Handheld" also says how the camera was held
OLD_SUPPORT = {"Handheld": SUPPORTS["handheld_subtle"]}


def normalise(field: str, value: str) -> str:
    """A stored value in today's panel words: an old move ("Dolly in") becomes its new label ("Push in")."""
    return OLD.get(field, {}).get(value, value)


def label_of(field: str, slug: str) -> str:
    """The panel's label for an agent's slug ("push_in" -> "Push in"); the slug itself when the field has no table."""
    table = {"movement": {m.slug: m.label for m in MOVES}, "support": SUPPORTS, "speed": SPEEDS, "framing": SIZES,
             "angle": ANGLES, "height": HEIGHTS, "focus": FOCUS, "composition": COMPOSITIONS, "time": TIMES,
             "axis": AXES}.get(field)
    return table.get(slug, slug) if table else slug


def slug_of(field: str, label: str) -> str:
    """The agent's slug for a panel label ("Push in" -> "push_in"); "" when there is none."""
    label = normalise(field, label)
    table = {"movement": {m.label: m.slug for m in MOVES}, "support": {v: k for k, v in SUPPORTS.items()},
             "speed": {v: k for k, v in SPEEDS.items()}, "framing": {v: k for k, v in SIZES.items()},
             "angle": {v: k for k, v in ANGLES.items()}, "height": {v: k for k, v in HEIGHTS.items()},
             "focus": {v: k for k, v in FOCUS.items()}, "composition": {v: k for k, v in COMPOSITIONS.items()},
             "time": {v: k for k, v in TIMES.items()}, "axis": {v: k for k, v in AXES.items()}}.get(field, {})
    return table.get(label, "")


# ── the knowledge base mapping (lab kb.py) ───────────────────────────────────────────────────────────────────────────

FOCUS_TERM: dict[str, str] = {"rack_focus": "rack_focus_pull_focus", "focus_follow": "follow_focus_2",
                              "shallow_isolation": "shallow_focus", "deep": "deep_focus"}
# moves the base has no row for: what they do, when to use them
OWN: dict[str, str] = {
    "breathing": "the frame floats and sways a little, as on an operator's shoulder. MEASURED: Omni renders it as a "
                 "still frame; counts as a hold.",
    "drift": "a slow sideways or forward float of a few inches. MEASURED: Omni renders it as a still frame; counts as "
             "a hold.",
    "reframe": "a small pan/tilt correction as people shift. Use: when someone moves inside the shot; counts as a "
               "hold.",
    "push_then_hold": "a push that lands and stays. Use: a line or realisation that must land, then sit.",
    "track_then_hold": "travel with a person, then stop as they stop. Use: arrivals, a walk that ends in a meeting.",
    "push_past_foreground": "move through a foreground object (a doorway, a shoulder, leaves) toward the subject. "
                            "Use: entering a private moment, discovery.",
}
VARIANT: dict[str, str] = {
    "pull_back_reveal": "pulling back", "lead": "moving ahead of the person, backward", "follow": "behind them",
    "tracking_alongside": "beside them", "half_orbit": "half a circle", "crane_up": "rising",
    "crane_down": "descending", "slow_zoom": "slow, almost a creep", "snap_zoom": "fast",
    "crash_zoom": "fast, violent", "whip_out": "first half of a whip transition", "whip_in": "second half",
    "follow_pan": "turning with a moving person", "slow_pan_reveal": "slow, discovering",
    "aerial_pull_away": "pulling away and up", "focus_out": "defocus out (transition)",
    "focus_in": "focus in (transition)", "shake": "impact shake",
}

# ── what the video model does (D7) ───────────────────────────────────────────────────────────────────────────────────

OMNI_MEASURED = (
    "MEASURED on Omni 1.2 Flash, 360p, text to video (lab/camera_agent renders, 2026-11-20), background motion over "
    "the take:\n"
    "- push_in / push_then_hold on a face, also while she speaks: PERFORMED clearly (MS -> MCU).\n"
    "- push_then_hold on a two-shot: PERFORMED (full figures -> waist up, then settles).\n"
    "- A float in a two-shot is NOT performed, however it is worded: \"gently floating and swaying\", \"handheld "
    "camera with a slight natural shake\", \"drifts slowly sideways to the right\" all came out as still as \"a "
    "steady frame on a tripod\". Do not rely on breathing / drift / handheld_subtle for life; they count as holds.\n"
    "MEASURED from a first frame (lab/camera_moves and lab/shot_prompts, reference_to_video, 2026-11-20):\n"
    "- push_in and push_then_hold on a single and on a two-shot, slow_creep, and pull_out: PERFORMED (the size "
    "changes).\n"
    "- arc_right on two people, written with its visible result (\"the camera arcs slowly to the right around them, "
    "the office sliding past behind\"): PERFORMED, the strongest motion of all takes. A sideways move whose sentence "
    "does not say what changes on screen renders still: always name the visible result.\n"
    "- The ANGLE and HEIGHT come from the first frame, not from the video sentence: they are drawn into the frame."
)


def omni_brief() -> str:
    """The <omni> part of the agent's brief, from the table."""
    provisional = ", ".join(m.slug for m in MOVES if m.omni == "provisional" and m.family != "still")
    risky = ", ".join(m.slug for m in MOVES if m.omni == "risky")
    return ("<omni>\n" + OMNI_MEASURED + "\n"
            f"PROVISIONAL (not measured yet): {provisional}.\n"
            f"Risky (may be ignored or warp faces; use only with a strong reason, never on a speaking face; mark "
            f"`omni` risky): {risky}; rack_focus (the model often ignores a timed focus change); slow_motion; "
            "timelapse; hyperlapse.\n</omni>")


def omni_of(move: str) -> str:
    """"works" or "risky", as the agent's `omni` field says it."""
    m = MOVE.get(move)
    return "risky" if m is not None and m.omni == "risky" else "works"
