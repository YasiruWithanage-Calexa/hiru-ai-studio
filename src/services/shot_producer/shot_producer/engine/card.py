"""Reading a shot's director's card (`shots.card`, Shot Planner Adam, plan/2026-11-04b Phase 7) as plain JSON.

A shot the classic planner made has no card (`{}`) and none of this applies. A shot with a card already says what it
is FOR, what we see, who is seen and who is only heard, how the camera behaves and what the soundtrack does, so:

* the intent agent is skipped: `adam_write` stores an intent with `by = "adam"`, which no agent replaces;
* the DoP is told the card's camera decisions as fixed, and the recommendation takes the ones the panel has words for;
* the card's performance per beat is kept (`fit_beats`), like a person's beat notes;
* its sound design reaches the Veo prompt (`sound_text`), and a card that asks for silence has silence stated.

This module reads dictionaries only: it knows the card's keys, not the classes that write it, so what is shared here
does not import from the `adam` folders (plan §5.0). `steps/serialize/card.py` is a copy of this file.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Row = dict[str, Any]

# The panel's words (contracts.producer.CAMERA_OPTIONS) for the card's camera fields that have an exact equivalent.
# A field with none (a crane, a dutch angle) is left to the DoP, who is told the card's words.
ANGLE = {"eye": "Eye level", "low": "Low angle", "high": "High angle"}
LENS = {"wide": "28mm", "normal": "50mm", "long": "85mm"}
MOVEMENT = {"static": "Static", "push_in": "Dolly in", "pull_out": "Dolly out", "pan": "Pan", "handheld": "Handheld"}
APERTURE = {"shallow": "f/2", "rack": "f/2", "deep": "f/5.6"}


def _part(card: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """A nested object of the card, or an empty one."""
    found = card.get(key)
    return found if isinstance(found, dict) else {}


def of(shot: Mapping[str, Any] | None) -> Row:
    """The stored shot's card, or `{}` for a shot without one."""
    card = (shot or {}).get("card")
    return card if isinstance(card, dict) and card.get("size") else {}


def camera(card: Mapping[str, Any]) -> dict[str, str]:
    """The camera fields the card decides, in the panel's words. A recommendation never changes the shot's size."""
    out: dict[str, str] = {}
    if card.get("angle") in ANGLE:
        out["angle"] = ANGLE[str(card["angle"])]
    if card.get("lens_feel") in LENS:
        out["lens"] = LENS[str(card["lens_feel"])]
    if card.get("movement") in MOVEMENT:
        out["movement"] = MOVEMENT[str(card["movement"])]
    focus = _part(card, "focus")
    if focus.get("kind") in APERTURE:
        out["aperture"] = APERTURE[str(focus["kind"])]
    return out


def _bit(label: str, value: Any) -> str:
    text = " ".join(str(value or "").split())
    return f"{label}: {text}" if text and text != "{}" else ""


def decisions_text(card: Mapping[str, Any]) -> str:
    """What the DoP is told about a card shot: the director's camera, as decisions. Empty without a card."""
    if not card:
        return ""
    focus = _part(card, "focus")
    focus_text = str(focus.get("kind") or "")
    if focus_text == "rack":
        focus_text = f"rack from {focus.get('from') or '?'} to {focus.get('to') or '?'}"
    comp = _part(card, "composition")
    bits = [_bit("angle", card.get("angle")), _bit("height", card.get("height")), _bit("lens", card.get("lens_feel")),
            _bit("movement", str(card.get("movement") or "").replace("_", " ")), _bit("focus", focus_text),
            _bit("foreground", comp.get("foreground")), _bit("negative space", comp.get("negative_space")),
            _bit("subject on the", comp.get("frame_side")), _bit("looking", card.get("eyeline")),
            _bit("blocking", card.get("blocking_in_shot"))]
    said = "; ".join(b for b in bits if b)
    return f"DIRECTOR'S CAMERA, FROM THE SHOT CARD (fixed; express it, do not change it): {said}." if said else ""


def sound_text(card: Mapping[str, Any]) -> str:
    """The card's sound design as one sentence for the prompt ('' when it has none)."""
    sound = _part(card, "sound")
    bits = [_bit("room", sound.get("ambience")), _bit("effects", sound.get("effects")),
            _bit("music", sound.get("music")), _bit("this sound arrives before its picture", sound.get("pre_lap")),
            _bit("it carries into the next shot", sound.get("carries_over"))]
    return "; ".join(b for b in bits if b)


def silent(card: Mapping[str, Any]) -> bool:
    return bool(_part(card, "sound").get("silence"))


def voiced_off(card: Mapping[str, Any]) -> list[str]:
    """Ids (the agents' line ids) of the lines this card plays over someone else's face."""
    return [str(ln.get("line_id")) for ln in card.get("lines") or [] if isinstance(ln, dict)
            and ln.get("line_id") and ln.get("on_speaker") is False]
