"""The camera panel in a prompt's words (plan/2026-11-11b, revised 2026-11-11; rewritten for the camera catalogue by
plan/2026-11-20c D13): every field a person sees on the shot's camera card is in both prompts, as it stands now.

The PANEL is the authority: what it shows is what the prompt says, so a person's change reaches the next prompt. The
Camera agent's own sentence (`design.camera.camera_sentence`) is the camera of a video prompt while a person has not
changed a camera field (`camera_line`); after a change, code writes it from the fields. A hold says "holds still", a
move says what the camera does ("the camera slowly pushes in"). Camera gear is never named: the video model draws
whatever is named into the picture (render 007). Lens and stop are given as numbers AND as what they look like.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from contracts import camera as cam
from contracts.producer import CameraField, CameraSettings, is_hold

Row = dict[str, Any]

# A support that is felt in the picture and is not gear: said. Everything else (dolly, crane, gimbal...) never is.
HANDHELD = {"handheld_subtle": "handheld, calm", "handheld_urgent": "handheld and urgent", "shoulder": "handheld"}
ADVERB = {"very_slow": "very slowly", "slow": "slowly", "medium": "", "fast": "quickly", "snap": "sharply",
          "none": ""}
# Camera words that name gear (contracts.camera_words never writes them; a gate refuses them in the agent's sentence)
GEAR = re.compile(r"\b(tripod|sticks|dolly|slider|crane|jib|gimbal|steadicam|stabili[sz]er|rig|drone|rails?|"
                  r"camera operator|operator)\b", re.I)


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def _cine(ir: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = ir.get("cinematography")
    return raw if isinstance(raw, Mapping) else {}


def changed(camera: CameraSettings, recommended: CameraSettings | None, f: CameraField) -> bool:
    """A person set this field by hand (the camera as it stands differs from the recommendation)."""
    return recommended is not None and getattr(camera, f.value) != getattr(recommended, f.value)


def any_changed(camera: CameraSettings, recommended: CameraSettings | None) -> bool:
    return any(changed(camera, recommended, f) for f in CameraField)


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


def move_phrase(camera: CameraSettings) -> str:
    """"the camera slowly pushes in" / "the camera holds still": the move and its speed, no gear."""
    slug = cam.slug_of("movement", camera.movement)
    move = cam.MOVE.get(slug)
    if move is None or slug in cam.STILL_MOVES:
        return "the camera holds still"
    adverb = ADVERB.get(cam.slug_of("speed", camera.speed), "")
    return f"the camera {adverb + ' ' if adverb else ''}{move.words}"


def move_words(camera: CameraSettings, *, still: bool) -> str:
    """The movement and its speed: for a still, the frame it opens on; for a clip, the move."""
    held = HANDHELD.get(cam.slug_of("support", camera.support), "")
    lead = f"Handheld ({held}): " if held else ""
    if is_hold(camera):
        return f"{lead}{'The' if not lead else 'the'} camera holds still: a steady, unmoving frame."
    phrase = move_phrase(camera)
    if still:
        return f"{lead}This is the opening frame of the move: from here {phrase}."
    text = f"{phrase}, one smooth move."
    return f"{lead}{text if lead else text[0].upper() + text[1:]}"


def axis_words(camera: CameraSettings) -> str:
    if cam.slug_of("axis", camera.axis) == "crossing_on_screen":
        return "The camera crosses the line of action on screen, as it moves."
    side, _, direction = camera.axis.partition(" · ")
    return f"Camera on {side[:1].lower()}{side[1:]} of the line of action: the action reads {direction or 'as staged'}."


def extra_words(camera: CameraSettings) -> str:
    """The optional fields that change the picture: height, focus, composition, time ("" when none is set)."""
    out = []
    if camera.height:
        out.append(f"camera at {camera.height.lower()}")
    if camera.composition:
        out.append(f"composed {camera.composition.lower()}")
    if camera.time and cam.slug_of("time", camera.time) != "normal":
        out.append(camera.time.lower())
    return f"{'; '.join(out)[:1].upper()}{'; '.join(out)[1:]}." if out else ""


def camera_words(camera: CameraSettings, recommended: CameraSettings | None, ir: Mapping[str, Any], *,
                 still: bool, design: Mapping[str, Any] | None = None) -> str:
    """Every camera field of the panel, as it stands, with the planner's detail where the person left the field.
    `design`: the Camera agent's design (`shots.design.camera`, D5): while the person has not changed the move, a
    clip's move is the agent's sentence, and the first frame opens on what it opens on (D14)."""
    cine = _cine(ir)
    keep = {f: not changed(camera, recommended, f) for f in CameraField}
    agent = dict(design or {})
    framing = _with(camera.framing, _clean(cine.get("framing")) if keep[CameraField.FRAMING] else "")
    angle = _with(camera.angle.lower(), _lower_first(_clean(cine.get("angle")))
                  if keep[CameraField.ANGLE] and not agent else "")
    mm = int(re.sub(r"\D", "", camera.lens) or 50)
    dof = _clean(cine.get("depth_of_field")).rstrip(".") if keep[CameraField.APERTURE] and not agent else ""
    focus = (dof if dof else "a rack focus within the shot" if cam.slug_of("focus", camera.focus) == "rack_focus"
             else "shallow focus: the subject sharp, the background melting into soft blur"
             if shallow(camera.aperture) else "deep focus: sharp from front to back")
    out = [f"{framing}, {angle}; {camera.lens} lens at {camera.aperture}, {lens_look(mm)}; focus: {focus}."]
    extra = extra_words(camera)
    if extra:
        out.append(extra)
    moved = keep[CameraField.MOVEMENT] and keep[CameraField.SPEED] and keep[CameraField.SUPPORT]
    sentence = _clean(agent.get("camera_sentence"))
    if still and agent.get("opens_on") and moved and not is_hold(camera):
        out.append(f"This is the opening frame of the move: {_clean(agent['opens_on']).rstrip('.')}.")
    elif not still and sentence and moved:
        out.append(sentence if sentence.endswith(".") else f"{sentence}.")
    else:
        out.append(move_words(camera, still=still))
        planner_move = _clean(cine.get("movement")).rstrip(".")
        # the planner's own words only while nothing else says the camera (no agent) and they cannot contradict a hold
        if planner_move and moved and not still and not agent and not is_hold(camera):
            out.append(f"As planned: {_lower_first(planner_move)}.")
    out.append(axis_words(camera))
    return " ".join(out)


def sentence_from_fields(camera: CameraSettings) -> str:
    """The camera sentence code writes after a person changed a field (D13): size and angle, how it is held when that
    shows, the move. No gear, no clock, at most about 200 characters."""
    held = HANDHELD.get(cam.slug_of("support", camera.support), "")
    angle = camera.angle.lower()
    height = f" from {camera.height.lower()}" if camera.height else ""
    lead = f"{camera.framing}, {angle}{height}{', ' + held if held else ''}"
    move = "the camera holds still" if is_hold(camera) else move_phrase(camera)
    return f"{lead}: {move}."


def camera_line(camera: CameraSettings, recommended: CameraSettings | None, design: Mapping[str, Any] | None) -> str:
    """The Camera section of a video prompt (D13): the agent's sentence while the person has not changed a camera
    field, else code's sentence from the fields as they stand."""
    sentence = _clean((design or {}).get("camera_sentence"))
    if sentence and not any_changed(camera, recommended):
        return sentence if sentence.endswith(".") else f"{sentence}."
    return sentence_from_fields(camera)


def lighting_words(camera: CameraSettings, recommended: CameraSettings | None, planner_light: str) -> str:
    """The panel's lighting, and the planner's light for this shot while the person has not changed the lighting
    (a person's choice replaces the planner's light: both together would contradict)."""
    planner_light = _clean(planner_light).rstrip(".")
    if changed(camera, recommended, CameraField.LIGHTING) or not planner_light:
        return f"{camera.lighting}."
    # The preset's source ("window light", "open sun") is a guess from the heading, which often names no INT or EXT
    # ("SCENE 03 — THE UNEXPECTED ENCOUNTER" gave "window light" on an open road, 2026-11-18): the planner's light says
    # the source, the preset keeps the time of day
    return f"{camera.lighting.split(',')[0]}: {planner_light}."
