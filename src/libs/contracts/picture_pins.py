"""What a frame, a video prompt and a shot prompt were made against on the CAMERA side (plan/2026-11-20d D8).

    picture(camera, design, opening="")          -> the fields that shape the still: size, angle, height, lens, stop,
                                                    focus, composition, the side of the line, the lighting, the Camera
                                                    agent's opening picture; on a frame, the shot prompt's opening
    motion(camera, recommended, design)          -> the fields that shape the motion: move, speed, timing, trigger,
                                                    where it lands, the end size, the camera sentence
    pinned(pins, camera, recommended, design)    -> `pins` with both set (a dict, as stored)

A FRAME is out of date when `picture` moved; a VIDEO PROMPT when `picture` or `motion` moved; a SHOT PROMPT when either
moved or the script, the cast or the looks did (`contracts.producer.stale_reasons`, which names each field that moved,
before → after). A move-only change keeps the frame. Nothing is redrawn or rewritten here: the reasons are shown, a
person clicks.

`design` is the Camera agent's block on the shot (`contracts.frame_brief.agent_camera`), None for a shot it did not
design. Long text (the opening picture, where it lands, the sentence, the opening state) is pinned as a short hash.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from contracts.camera_words import camera_line
from contracts.producer import CameraSettings, Pins

PICTURE_FIELDS = ("framing", "angle", "height", "lens", "aperture", "focus", "composition", "axis", "lighting")
MOTION_FIELDS = ("movement", "speed")
MOTION_BLOCK = ("start_s", "end_s", "trigger", "end_size")


def short(text: Any) -> str:
    """A short, stable hash of a text (whitespace ignored); "" for no text."""
    body = " ".join(str(text or "").split())
    return hashlib.sha256(body.encode()).hexdigest()[:12] if body else ""


def picture(camera: CameraSettings, design: Mapping[str, Any] | None, opening: str = "") -> dict[str, str]:
    """The picture pin. `opening`: the shot prompt's opening state a frame is drawn from (a frame's pin only)."""
    out = {f: str(getattr(camera, f) or "") for f in PICTURE_FIELDS}
    out["opens_on"] = short((design or {}).get("opens_on"))
    if opening:
        out["opening"] = short(opening)
    return out


def motion(camera: CameraSettings, recommended: CameraSettings | None, design: Mapping[str, Any] | None
           ) -> dict[str, str]:
    """The motion pin: the panel's move and speed, the design's timing, trigger, landing and end size, and the camera
    sentence the video prompt gets (the agent's while no camera field changed, else code's)."""
    block = design or {}
    out = {f: str(getattr(camera, f) or "") for f in MOTION_FIELDS}
    out |= {k: str(block.get(k) if block.get(k) is not None else "") for k in MOTION_BLOCK}
    out["lands_on"] = short(block.get("lands_on"))
    out["sentence"] = short(camera_line(camera, recommended, design))
    return out


def opening_text(opening: Any) -> str:
    """A shot prompt's opening state as one stable text (what a frame's pin hashes)."""
    if not isinstance(opening, Mapping):
        return ""
    people = opening.get("people") or []
    bits = [" ".join(str(p.get(k) or "") for k in ("name", "side", "facing", "posture", "hands", "expression"))
            for p in people if isinstance(p, Mapping)]
    return " | ".join([*bits, str(opening.get("background") or ""), str(opening.get("light") or "")]).strip(" |")


def pinned(pins: Pins | Mapping[str, Any], camera: CameraSettings, recommended: CameraSettings | None,
           design: Mapping[str, Any] | None, *, opening: str = "") -> dict[str, Any]:
    """`pins` (as stored) with the picture and motion pins of the camera as it stands."""
    base = pins.model_dump() if isinstance(pins, Pins) else dict(pins)
    return {**base, "picture": picture(camera, design, opening), "motion": motion(camera, recommended, design)}


__all__ = ["MOTION_FIELDS", "PICTURE_FIELDS", "motion", "opening_text", "picture", "pinned", "short"]
