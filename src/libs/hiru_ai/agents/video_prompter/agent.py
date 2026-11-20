"""video_prompter hooks (plan/2026-11-20b §3): ONE agent writes the direction of every video clip.

The lab (`lab/video_prompt`, gpt-6.1-sol at low effort) proved it: given the scene packet (who each line is said to, its
intent, the reader's delivery note, what each person wants and feels) and the clip's facts, it writes how each line is
said and to whom, what the listener does, the situation and the place's sound. It never sees a line it could change:
the `video_prompt` step puts each line's exact words in.

The message: the scene first, as its OWN message (`shared_message`), byte for byte the same for every clip of the
scene, so it caches; then the clip, then the cards code picked for it. On a repair the first answer and the faults
follow. No `fallback`: with no model the agent is not called (D4), and a failed call is the caller's to report (D3).
"""
from __future__ import annotations

from functools import cache
from pathlib import Path

from hiru_ai.agents.video_prompter.schema import Input

CARDS = Path(__file__).resolve().parent / "prompts" / "cards"
CARD_NAMES = ("dialogue", "phone", "silent", "detail", "sinhala_voice")


@cache
def card(name: str) -> str:
    """One craft card's text (prompts/cards/<name>.md); "" for a name there is no card for."""
    if name not in CARD_NAMES:
        return ""
    return (CARDS / f"{name}.md").read_text(encoding="utf-8").strip()


def shared_message(inp: Input) -> str:
    """The part every clip of the scene shares, sent before the clip's own message."""
    return inp.scene


def user_message(inp: Input) -> str:
    cards = "\n".join(t for t in (card(n) for n in inp.cards) if t)
    parts = [inp.clip, f"<cards>\n{cards}\n</cards>" if cards else ""]
    if inp.repair:
        parts += [f"<your_first_answer>\n{inp.previous}\n</your_first_answer>" if inp.previous else "",
                  "Code checked your answer and found:\n- " + "\n- ".join(inp.repair)
                  + "\nAnswer again, complete, with these fixed."]
    return "\n\n".join(p for p in parts if p)
