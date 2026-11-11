"""Safe depiction (plan/2026-11-10b): a death or violence word in a description never reaches a provider; one in a
spoken line is advice; every writer is told; nothing is ever rewritten."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from contracts import safe_depiction as sd
from contracts.video_gen import (
    RenderFacts,
    VideoOverrides,
    VideoSettings,
    check_render,
    resolve,
    spec_for,
    validate_render,
)

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "src" / "libs" / "hiru_ai" / "agents"

# The writers outside a planner group; each group's own tests hold its writers (tests/<group>/test_safe_depiction.py).
WRITERS = [
    AGENTS / "shot_writer" / "prompts" / "system.md",
    ROOT / "src" / "services" / "shot_producer" / "shot_producer" / "engine" / "shots.py",
]


def words(text: str) -> list[str]:
    return [f.word for f in sd.blocking(text)]


@pytest.mark.parametrize("text, word", [
    ("A dead man lies on the floor.", "dead"),
    ("Police stand over the corpse.", "corpse"),
    ("Her hand is bloodied.", "blood"),
    ("The floor is clean, no blood anywhere.", "blood"),  # negated still names it
    ("He was stabbed in the alley.", "stab"),
    ("The killer waits.", "kill"),
    ("Evidence of the MURDER is on the desk.", "murder"),
    ("A body bag on a stretcher.", "body bag"),
    ("Her wounded arm hangs.", "wound"),
    ("The scene of his death.", "death"),
    ("She died an hour ago.", "died / dying"),
    ("A bullet wound in the door.", "wound"),
])
def test_a_listed_word_in_the_description_blocks(text: str, word: str):
    assert word in words(text)


@pytest.mark.parametrize("text", [
    "The dead of night; a lamp burns low.",
    "A dead end lane, wet with rain.",
    "He stands dead still in the doorway.",
    "She is wound up, pacing the room.",
    "The road wound through the tea estate.",
    "The dying light of evening falls on her face.",
    "Close shot on her body language as she turns away.",
    "A wide shot, locked off, of the market.",
    "A man lies still on the floor, eyes closed, one arm stretched out.",
    "A white sheet over a shape on a stretcher.",
])
def test_harmless_shot_language_passes(text: str):
    assert words(text) == []


def test_a_word_inside_a_spoken_line_is_advice_never_a_block():
    text = 'Kamala says (softly), "He is dead." — only Kamala\'s lips move. A curly “murder” too.'
    found = sd.scan(text)
    assert sd.blocking(text) == []
    assert {f.word for f in found if f.spoken} == {"dead", "murder"}


def test_sinhala_lines_are_never_matched():
    assert sd.scan('Nimal says, "ඔහු මැරිලා." — only Nimal\'s lips move.') == []


def test_scan_reports_each_term_once_with_the_words_as_written():
    found = sd.blocking("Blood on the wall, blood on the floor, a BLOODY hand.")
    assert [(f.word, f.said) for f in found] == [("blood", "Blood")]


def _spec(prose: str, negative: str = ""):
    resolved = resolve(VideoSettings(engine="veo_3_1"), None, VideoOverrides(negative_prompt=negative or None),
                       production_aspect="16:9", shot_seconds=8)
    return spec_for(resolved, prose=prose, references=[])


def test_the_video_request_is_blocked_with_the_word_and_a_way_out():
    fails = [c.label for c in validate_render(_spec("A corpse lies in the paddy field.")) if c.tone == "fail"]
    assert len(fails) == 1 and "“corpse”" in fails[0] and "a figure lying still" in fails[0]


def test_a_negative_prompt_may_name_what_must_stay_out():
    spec = _spec("A man lies still on the floor, eyes closed.", negative="blood, gore")
    assert [c for c in validate_render(spec) if "Google's video models" in c.label] == []


def test_a_spoken_word_is_an_advisory_on_the_bound_request_and_the_prose_is_untouched():
    prose = 'Nimal (the man in a white shirt) says, "They killed him." — only Nimal\'s lips move.'
    spec = _spec(prose)
    assert not [c for c in validate_render(spec) if "Google's" in c.label]
    advice = [c for c in check_render(spec, RenderFacts()) if c.tone == "advisory"]
    assert any("A spoken line says “killed”" in c.label for c in advice)
    assert spec.prose == prose


def test_frame_error_names_the_words_and_says_nothing_was_spent_on_them():
    msg = sd.frame_error(sd.blocking("A corpse, blood on the tiles."))
    assert msg.startswith("Not painted:") and "“corpse”" in msg and "“blood”" in msg


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def told(path: Path) -> bool:
    """The prompt carries the line word for word (it may wrap; Adam's carry it as a paragraph, not a bullet)."""
    text, line = _norm(path.read_text(encoding="utf-8")), _norm(sd.PROMPT_LINE)
    return line in text or line[2:] in text


@pytest.mark.parametrize("path", WRITERS, ids=lambda p: p.parent.parent.name if p.suffix == ".md" else p.stem)
def test_every_writer_is_told_the_rule_word_for_word(path: Path):
    assert told(path)


def test_every_prompt_that_carries_the_tag_has_the_whole_line_unchanged():
    tag = "SAFE DEPICTION (plan/2026-11-10b)"
    tagged = [p for p in AGENTS.rglob("system*.md") if tag in p.read_text(encoding="utf-8")]
    assert len(tagged) >= 9  # shot_writer and the planner groups' writers
    assert [p for p in tagged if not told(p)] == []


def test_the_knowledge_base_has_the_guidance():
    kb = ROOT / "src" / "libs" / "hiru_ai" / "knowledge_bases" / "rules"
    assert (kb / "sources" / "safe_depiction.md").exists()
    assert "safe_depiction.md" in (kb / "component.yaml").read_text(encoding="utf-8")
