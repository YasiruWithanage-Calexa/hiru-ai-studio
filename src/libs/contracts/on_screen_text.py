"""Text inside the picture (plan/2026-11-17b): the video model renders it, so it is written out, never avoided.

The person's decision (2026-11-17): Omni Flash 1.1 and 1.2, the engines Hiru renders with, draw readable text (a
phone's message, a sign, a letter, a page) from the words in the prompt and from a picture that shows them. An old
Veo-lab belief (that Veo cannot draw text, so a phone is shown only as light on a face) was copied into every planner's
checks and prompts, the knowledge bases and the video prompt's rendering constraints, and it came back after it was
struck for Raphael alone (2026-11-08). This module is the ONE place the rule lives.
`tests/contracts/test_on_screen_text.py` fails when the old belief is written again anywhere in `src/` or a lab prompt,
and when a planner prompt drifts from `PLANNER`.

    PLANNER  what a planner or a shot writer is told: give the exact words, in the script's language
    CRITIC   what a critic of a plan is told: text in the picture is not a fault
    VIDEO    the line in every video prompt's rendering constraints (it replaced `lettering_clean`)
    FRAME    the line in every first-frame picture's closing
"""

from __future__ import annotations

PLANNER = (
    "Text inside the picture is welcome: the video model renders readable text on a phone, a screen, a sign, a "
    "letter or a page. When a shot shows such text, write its exact words as the script gives them, in the "
    "script's language, and say where they are."
)

CRITIC = (
    "Text inside the picture (a phone's message, a sign, a letter) is not a fault: the video model renders "
    "readable text. Ask only that its exact words are given."
)

VIDEO = (
    "Text the description spells out (on a screen, a sign, a letter or a page) is rendered exactly as written; "
    "no other lettering is invented."
)

FRAME = "Text the brief spells out is drawn exactly as written; no other lettering is added."
