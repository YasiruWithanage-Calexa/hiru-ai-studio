"""Text inside the picture stays allowed (plan/2026-11-17b, `contracts.on_screen_text`).

The video model renders readable text (Omni Flash 1.1 / 1.2, from the prompt's words and from a picture). An old Veo-lab
belief (that Veo cannot draw text) was copied into every planner and came back after it was struck for Raphael
alone (2026-11-08). These tests stop it coming back: a banned phrase anywhere in `src/` or a lab prompt fails the suite,
and every planner prompt carries the contract's own sentence, word for word.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from contracts import frame_brief, on_screen_text

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "src" / "libs" / "hiru_ai" / "agents"

# The old belief in the shapes it was written. Lower case; matched case-insensitively, whitespace folded.
BANNED = (
    "cannot render readable text",
    "can't render readable text",
    "cannot do readable",
    "readable screen text",
    "readable text on a screen",
    "glow of the screen on a face",
    "phone's light on a face",
    "free of lettering",
    "rendered as gibberish",
    "renders as gibberish",
    "add the text in post",
    "reaction instead of text",
    "reaction instead of the text",
    "avoid readable text",
    "risky for text",
)
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".txt"}
# Where the rule could be written for a model or a check to read. Lab RUNS are history (what a model once said) and are
# never read back; lab prompts are where new planners are copied from, so they are guarded.
SCANNED = [ROOT / "src", *sorted((ROOT / "lab").glob("*/prompt")), *sorted((ROOT / "lab").glob("*/prompts"))]
SKIP_PARTS = {"__pycache__", "node_modules", ".venv", "runs"}

# Every prompt that plans or writes shots: each carries `on_screen_text.PLANNER`, word for word.
PLANNER_PROMPTS = (
    "zora/zora_author/prompts/system.md",
    "jonathan/jonathan_author/prompts/system.md",
    "jonathan/jonathan_revise/prompts/system.md",
    "david/david_author/prompts/system.md",
    "raphael/raphael_planner/prompts/system.md",
    "raphael/raphael_cinematic/prompts/system.md",
    "adam/adam_director/prompts/system.md",
    "adam/adam_shot_designer/prompts/system.md",
    "adam/adam_take/prompts/system.md",
)
CRITIC_PROMPTS = (
    "adam/adam_critic/prompts/system.md",
    "adam/adam_critic_fidelity/prompts/system.md",
)


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'")).lower()


def _files() -> list[Path]:
    out = []
    for base in SCANNED:
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in TEXT_SUFFIXES and not SKIP_PARTS & set(p.parts):
                out.append(p)
    return out


def test_the_old_belief_is_written_nowhere() -> None:
    this = Path(__file__).resolve()
    found = []
    for p in _files():
        if p.resolve() == this:
            continue
        text = _fold(p.read_text(encoding="utf-8", errors="ignore"))
        found += [f"{p.relative_to(ROOT)}: {phrase!r}" for phrase in BANNED if phrase in text]
    assert not found, (
        "The video model renders readable text (plan/2026-11-17b). Do not tell a model or a check otherwise; "
        "use contracts.on_screen_text instead:\n" + "\n".join(found)
    )


@pytest.mark.parametrize("prompt", PLANNER_PROMPTS)
def test_every_planner_prompt_carries_the_rule_word_for_word(prompt: str) -> None:
    text = _fold((AGENTS / prompt).read_text(encoding="utf-8"))
    assert _fold(on_screen_text.PLANNER) in text, f"{prompt} must carry contracts.on_screen_text.PLANNER"


@pytest.mark.parametrize("prompt", CRITIC_PROMPTS)
def test_every_critic_prompt_carries_the_rule_word_for_word(prompt: str) -> None:
    text = _fold((AGENTS / prompt).read_text(encoding="utf-8"))
    assert _fold(on_screen_text.CRITIC) in text, f"{prompt} must carry contracts.on_screen_text.CRITIC"


def test_the_first_frame_asks_for_the_text_and_never_bans_it() -> None:
    assert on_screen_text.FRAME in frame_brief.CLOSE_SINGLE
    assert "no text" not in frame_brief.CLOSE_SINGLE.lower()


# That no planner's check REPORTS text in the picture is tested in each group's own folder (a group's modules may not be
# imported from here): tests/jonathan/test_checks.py, tests/david/test_checks.py, tests/raphael/test_checks.py and
# steps/adam/adam_feasibility/tests.
