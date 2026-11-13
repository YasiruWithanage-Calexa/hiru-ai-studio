"""Tests that live with the coverage_kernel step (ADR 0006)."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.coverage_kernel import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_silent_clip_is_voiced_and_locked_as_the_persons() -> None:
    out = step.run(EXAMPLE)
    assert [a["text"] for a in out["applied"]] == ["S03 · sound mode: silent → dialogue"]
    assert "[locked: sound_mode]" in out["clips"][2]


def test_a_removed_line_clip_hands_its_line_to_a_clip_that_shows_the_speaker() -> None:
    out = step.run({**EXAMPLE, "ops": [{"op": "remove", "shot": "S02"}], "by": "conductor"})
    assert out["notes"] == ["L1 (Anudi's line) moves to the master WIDE [1A-1], which shows Anudi"]
    assert "performs L1 (Anudi)" in out["clips"][0]


def test_an_unknown_shot_is_refused_and_nothing_moves() -> None:
    out = step.run({**EXAMPLE, "ops": [{"op": "retime", "shot": "S09", "take_s": 8}]})
    assert out["rejected"][0]["reason"] == "there is no shot S09" and not out["applied"]
