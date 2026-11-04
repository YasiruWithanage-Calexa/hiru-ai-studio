"""prompt_lint: a stored video prompt held up to the rules of the clip schema and the Veo guide (plan/2026-11-04 §5.2).

Everything here is read from the prompt row and the shot; nothing is regenerated and no model is asked. Findings:

  missing_section  a section the schema always writes is absent (voices only when the shot speaks, join only on a join)
  duration         the Format section states a length other than the shot's
  line_changed     a spoken line of the shot is not in the prompt word for word (dialogue is never reworded)
  too_long         the prompt is longer than the video model reads (about 1,024 tokens)
  failed_check     a check stored with the prompt came out `fail`

A shot with a director's card (`shots.card`, Shot Planner Adam, plan/2026-11-04b Phase 7) is also held to what the card
decided:

  silence_unstated      the card asks for silence and the prompt does not say so (Veo then invents speech or music)
  voice_not_off_screen  the card plays a line over a listener's face and the prompt does not say the voice is off screen
  performance_dropped   a beat's performance (what the face and body do) is not in the prompt
  sound_cue_missing     the card's effects are not in the prompt
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from hiru_ai.core.tokens import tokens_of

REQUIRED = ("style", "camera", "action", "constraints", "format")
SPOKEN = ("dialogue", "voiceover", "sung")
MAX_TOKENS = 1024  # the Veo prompt limit
DURATION = re.compile(r"Duration\s+(\d+)\s+seconds", re.IGNORECASE)
OFF_SCREEN = re.compile(r"off[- ]?screen|heard,? (?:but )?not seen|never in frame|not shown speaking", re.IGNORECASE)
SHARE = 0.6  # a performance or a cue is "in" the prompt when this share of its words are


def _flat(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def _finding(kind: str, message: str) -> dict[str, str]:
    return {"code": kind, "message": message}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W_]+", _flat(text).lower()) if len(w) > 3]


def _in_prompt(text: str, prose: str) -> bool:
    """The text, or most of its words, is in the prose: the writer may reorder or inflect, never drop."""
    if _flat(text).lower() in prose:
        return True
    words = _words(text)
    return not words or sum(w in prose for w in words) / len(words) >= SHARE


def card_findings(prompt: dict[str, Any], card: dict[str, Any]) -> list[dict[str, str]]:
    prose = _flat(prompt.get("prose") or "").lower()
    sound: dict[str, Any] = card["sound"] if isinstance(card.get("sound"), dict) else {}
    out: list[dict[str, str]] = []
    if sound.get("silence") and "silen" not in prose:
        out.append(_finding("silence_unstated", "the card asks for silence but the prompt never says so"))
    voiced_over = any(isinstance(ln, dict) and ln.get("on_speaker") is False for ln in card.get("lines") or [])
    if voiced_over and not OFF_SCREEN.search(prose):
        out.append(_finding("voice_not_off_screen", "the card plays a line over a listener but the prompt does not "
                                                    "say the voice is off screen"))
    for n, beat in enumerate(card.get("beats") or [], start=1):
        performance = beat.get("performance") if isinstance(beat, dict) else ""
        if performance and not _in_prompt(str(performance), prose):
            out.append(_finding("performance_dropped", f"beat {n}'s performance is not in the prompt: {performance!r}"))
    effects = str(sound.get("effects") or "")
    if effects and not _in_prompt(effects, prose):
        out.append(_finding("sound_cue_missing", f"the card's sound effects are not in the prompt: {effects!r}"))
    return out


def lint(prompt: dict[str, Any], shot: dict[str, Any], lines: list[dict[str, Any]]) -> list[dict[str, str]]:
    sections = {str(s.get("id")): s for s in prompt.get("sections") or []}
    shot_lines = [ln for ln in lines if str(ln.get("shot_id")) == str(shot.get("id"))]
    spoken = shot.get("sound_mode") in SPOKEN and bool(shot_lines)
    out: list[dict[str, str]] = []

    wanted = [*REQUIRED, *(["voices"] if spoken else []),
              *(["join"] if shot.get("camera_link", "cut") != "cut" else [])]
    out += [_finding("missing_section", f"the prompt has no {name} section") for name in wanted if name not in sections]

    fmt = " ".join(seg.get("text") or "" for seg in (sections.get("format") or {}).get("segments") or [])
    stated = DURATION.search(fmt)
    if stated and int(stated.group(1)) != int(shot.get("duration_s") or 0):
        out.append(_finding("duration", f"the prompt says {stated.group(1)} seconds but the shot runs "
                                        f"{shot.get('duration_s')} s"))

    said = {_flat(seg["sinhala"]) for s in sections.values() for seg in s.get("segments") or []
            if seg.get("sinhala") is not None}
    prose = _flat(prompt.get("prose") or "")
    for ln in shot_lines:
        text = _flat(ln.get("text") or "")
        if text and text not in said and text not in prose:
            out.append(_finding("line_changed", f"{ln.get('speaker') or 'a speaker'}'s line is not in the prompt word "
                                                f"for word: {ln.get('text')!r}"))

    size = tokens_of(str(prompt.get("prose") or ""))
    if size > MAX_TOKENS:
        out.append(_finding("too_long", f"the prompt is about {size} tokens; the video model reads about {MAX_TOKENS}"))

    out += [_finding("failed_check", str(c.get("label", ""))) for c in prompt.get("checks") or []
            if c.get("tone") == "fail"]
    card = shot.get("card")
    if isinstance(card, dict) and card.get("size"):
        out += card_findings(prompt, card)
    return out
