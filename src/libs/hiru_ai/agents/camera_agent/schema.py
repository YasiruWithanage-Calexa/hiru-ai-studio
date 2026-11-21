"""Typed seams of the Camera agent (plan/2026-11-20c §3). The agent decides the camera; the `camera_design` step builds
what it is given (the brief), checks its answer (the gates) and merges it into the shot's design. Every Literal is
`contracts.camera`'s list spelled out (a type checker needs it written); the agent's tests hold them equal, so the
schema, the checks and the panel cannot drift (D6).

The lab's `ClipCamera` / `SceneCamera` (lab/camera_moves/run.py, plan/2026-11-20d §6: moment, intensity, power,
angle_reason per clip; arc and peak_slate per scene). One output shape for both calls: a scene call answers
every clip; a one-shot call (an Ask, a clip a Zora or Sable turn changed) answers `clips` with that one clip only.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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
Size = Literal["ECU", "CU", "MCU", "MS", "MWS", "MLS", "WIDE", "EWS", "TWO", "OTS", "INSERT"]
Angle = Literal["eye_level", "slightly_low", "low", "slightly_high", "high", "overhead", "worms_eye", "dutch"]
Height = Literal["ground", "knee", "hip", "chest", "shoulder", "eye", "above_head", "aerial"]
Lens = Literal["18mm", "24mm", "28mm", "32mm", "35mm", "40mm", "50mm", "55mm", "65mm", "75mm", "85mm", "100mm",
               "135mm"]
Aperture = Literal["f/1.8", "f/2", "f/2.8", "f/4", "f/5.6", "f/8"]
Focus = Literal["shallow_isolation", "medium", "deep", "rack_focus", "focus_follow"]
Composition = Literal["rule_of_thirds", "centred", "foreground_framing", "negative_space", "frame_within_frame",
                      "over_shoulder", "symmetric", "lead_room"]
Time = Literal["normal", "slow_motion", "timelapse", "hyperlapse"]
Axis = Literal["side_a", "side_b", "crossing_on_screen"]


class ClipCamera(BaseModel):
    slate: str
    moment: Moment
    intensity: int = Field(description="1-5 on the scene's arc")
    power: str = Field(description="who holds the power in this clip, or 'equal' / 'none'")
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
    angle_reason: str = Field(description="why this angle and height; empty only for eye level between equals")
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
    """The agent's answer: the scene's camera language in one line, its arc, its peak clip, and a design per clip in
    the order asked."""

    camera_language: str
    arc: str
    peak_slate: str
    clips: list[ClipCamera]


class Input(BaseModel):
    """What the step built for one call."""

    # the scene, the toolbox and the video model's table: identical for every call of a scene, sent as its own message
    # first (it caches)
    scene: str
    clips: str  # the <clips> part: every clip of the scene in cut order
    # one-shot mode (an Ask, the clips a chat turn changed): the slates to answer for, the scene's camera as it stands
    focus: list[str] = Field(default_factory=list)
    current: str = ""  # the scene's camera so far (one line per clip), one-shot mode only
    language: str = ""  # the scene's camera language so far, one-shot mode only
    note: str = ""  # the person's words on an Ask
    repair: list[str] = Field(default_factory=list)  # the first answer's faults, on the repair call only
    previous: str = ""  # the first answer as JSON, on the repair call only
