"""shot_prompter hooks (plan/2026-11-20d §3): ONE agent writes a shot's first frame and its video together.

The lab (`lab/shot_prompts`, gpt-6.1-sol at medium effort) proved it on the person's own scene: from ONE opening state
(who is where, facing what, hands, expression, background, light) it writes the still's composition (the Camera agent's
angle and height in physical words, the framing at the move's start), its people, background and light, and the
video's situation, people, flow (lines by id) and sound. It never sees a line it could change: the `shot_prompt` step
puts each line's exact words in.

The message: the scene first, as its OWN message (`shared_message`), byte for byte the same for every shot of the
scene, so it caches; then the shot's facts, the camera design and the cards code picked; a person's video note
(plan/2026-11-22c: how the shot plays, never what it shows) as <video_note>. In video-only mode (D4 b) the stored
opening and frame follow as <fixed>. On a repair the first answer and the faults follow. No `fallback`: with no
model the agent is not called, and a failed call is the caller's to report.
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

from hiru_ai.agents.shot_prompter.schema import Input

CARDS = Path(__file__).resolve().parent / "prompts" / "cards"
CARD_NAMES = ("dialogue", "phone", "silent", "detail", "sinhala_voice")


@cache
def card(name: str) -> str:
    """One craft card's text (prompts/cards/<name>.md); "" for a name there is no card for."""
    if name not in CARD_NAMES:
        return ""
    return (CARDS / f"{name}.md").read_text(encoding="utf-8").strip()


def shared_message(inp: Input) -> str:
    """The part every shot of the scene shares, sent before the shot's own message."""
    return inp.scene


def user_message(inp: Input) -> str:
    cards = "\n".join(t for t in (card(n) for n in inp.cards) if t)
    parts = [inp.shot, inp.camera, f"<cards>\n{cards}\n</cards>" if cards else ""]
    if inp.video_note:
        parts += [f"<video_note>\n{inp.video_note}\n</video_note>",
                  "VIDEO NOTE: a person's direction for how this shot plays in its video (the voice, the delivery, "
                  "the pace, the mood, the motion). Follow it in the video's people, flow and sound. It never changes "
                  "the opening or the frame, a spoken line's words or the timecodes the shot's facts set."]
    if inp.mode == "video_only":
        parts += [f"<fixed>\n{inp.fixed}\n</fixed>",
                  "VIDEO ONLY: the first frame is already drawn from the opening and frame in <fixed>. Return them "
                  "exactly as given and write the video from them."]
    if inp.repair:
        parts += [f"<your_first_answer>\n{inp.previous}\n</your_first_answer>" if inp.previous else "",
                  "Code checked your answer and found:\n- " + "\n- ".join(inp.repair)
                  + "\nAnswer again, complete, with these fixed and nothing else changed."]
    return "\n\n".join(p for p in parts if p)
