"""The camera panel in a prompt's words (plan/2026-11-11b, revised 2026-11-11): every field a person sees on the shot's
camera card (framing, angle, lens, aperture, movement, speed, axis, lighting) is in both prompts, as it stands now.

The PANEL is the authority: what it shows is what the prompt says, so a person's change reaches the next prompt. The
planner's own words add detail beside a field only while the person has not changed that field (they describe the
planner's choice, and would contradict theirs). Lens and stop are given as numbers AND as what they look like.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from contracts.producer import CameraField, CameraSettings

Row = dict[str, Any]


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _cine(ir: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = ir.get("cinematography")
    return raw if isinstance(raw, Mapping) else {}


def changed(camera: CameraSettings, recommended: CameraSettings | None, f: CameraField) -> bool:
    """A person set this field by hand (the camera as it stands differs from the recommendation)."""
    return recommended is not None and getattr(camera, f.value) != getattr(recommended, f.value)


def lens_look(mm: int) -> str:
    """A focal length as what it does to the picture."""
    if mm <= 30:
        return "a wide lens: the space opens up around them, lines bending slightly at the frame edges"
    if mm <= 40:
        return "a wide-normal lens: natural perspective with some of the space around them"
    if mm <= 60:
        return "a normal lens: natural perspective, as the eye sees it"
    if mm <= 75:
        return "a slightly long lens: gentle compression, the background drawn a little closer"
    return "a long portrait lens: the background compressed and drawn close behind them"


def shallow(aperture: str) -> bool:
    return aperture in ("f/1.8", "f/2", "f/2.8")


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text else text


def _with(panel: str, planner: str) -> str:
    """"Medium close-up (MCU of Dinu's profile)": the panel's word, the planner's detail beside it when it adds any."""
    planner = planner.rstrip(".")
    return f"{panel} ({planner})" if planner and planner.lower() != panel.lower() else panel


def move_words(camera: CameraSettings, *, still: bool) -> str:
    """The movement and its speed: for a still, the frame it opens on; for a clip, the move."""
    speed = "" if camera.speed in ("None", "") else camera.speed.lower()
    if camera.movement == "Static":
        return "Static: a steady, locked-off frame."
    if camera.movement == "Handheld":
        pace = f", {speed} drift" if speed else ""
        return f"Handheld{pace}: the frame slightly off-level, held by a person."
    move = f"{speed + ' ' if speed else ''}{camera.movement.lower()}"
    return (f"{move[0].upper()}{move[1:]}: this is the opening frame of the move." if still
            else f"{move[0].upper()}{move[1:]}, one smooth move.")


def axis_words(camera: CameraSettings) -> str:
    side, _, direction = camera.axis.partition(" · ")
    return f"Camera on {side[:1].lower()}{side[1:]} of the line of action: the action reads {direction or 'as staged'}."


def camera_words(camera: CameraSettings, recommended: CameraSettings | None, ir: Mapping[str, Any], *,
                 still: bool) -> str:
    """Every camera field of the panel, as it stands, with the planner's detail where the person left the field."""
    cine = _cine(ir)
    keep = {f: not changed(camera, recommended, f) for f in CameraField}
    framing = _with(camera.framing, _clean(cine.get("framing")) if keep[CameraField.FRAMING] else "")
    angle = _with(camera.angle.lower(), _lower_first(_clean(cine.get("angle"))) if keep[CameraField.ANGLE] else "")
    mm = int(re.sub(r"\D", "", camera.lens) or 50)
    dof = _clean(cine.get("depth_of_field")).rstrip(".") if keep[CameraField.APERTURE] else ""
    focus = (dof if dof else "shallow focus: the subject sharp, the background melting into soft blur"
             if shallow(camera.aperture) else "deep focus: sharp from front to back")
    out = [f"{framing}, {angle}; {camera.lens} lens at {camera.aperture}, {lens_look(mm)}; focus: {focus}.",
           move_words(camera, still=still)]
    planner_move = _clean(cine.get("movement")).rstrip(".")
    if planner_move and keep[CameraField.MOVEMENT] and keep[CameraField.SPEED] and not still:
        out.append(f"As planned: {_lower_first(planner_move)}.")
    out.append(axis_words(camera))
    return " ".join(out)


def lighting_words(camera: CameraSettings, recommended: CameraSettings | None, planner_light: str) -> str:
    """The panel's lighting, and the planner's light for this shot while the person has not changed the lighting
    (a person's choice replaces the planner's light: both together would contradict)."""
    planner_light = _clean(planner_light).rstrip(".")
    if changed(camera, recommended, CameraField.LIGHTING) or not planner_light:
        return f"{camera.lighting}."
    return f"{camera.lighting}: {planner_light}."
