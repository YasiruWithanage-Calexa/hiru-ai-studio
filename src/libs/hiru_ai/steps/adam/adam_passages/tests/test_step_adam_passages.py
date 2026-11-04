"""adam_passages: the principles and devices that fit a scene, from the knowledge base's own files."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.adam.adam_passages import logic, step

HERE = Path(__file__).resolve().parents[1]


def test_the_example_runs_alone():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["kind"] == "devices" and out["text"].startswith("## ") and out["sources"]


def test_a_question_about_happiness_before_bad_news_finds_the_baseline_device_first():
    out = step.run({"kind": "devices", "query": "show a character happy and laughing before the bad news arrives, "
                                                "the state before the turn", "k": 3})
    assert out["sources"][0] == "devices/01-baseline-before-the-break.md" and len(out["sources"]) == 3


def test_a_phone_call_scene_finds_a_sound_device_in_its_top_eight():
    out = step.run({"kind": "devices", "query": "a phone call whose news narrows the room to her breath, "
                                                "the sound drops away", "k": 8})
    assert any("sound" in s or "silence" in s for s in out["sources"])


def test_the_grammar_always_ends_with_the_house_notes_which_are_a_labelled_draft():
    out = step.run({"kind": "grammar", "query": "a daughter obeys her father's call about marriage"})
    assert out["sources"][-1] == "house-drama-notes.md" and "DRAFT" in out["text"]
    assert len([s for s in out["sources"] if s.startswith("principles/")]) == logic.DEFAULT_K["grammar"]


def test_a_scene_with_nothing_to_match_still_gets_passages_in_name_order():
    out = step.run({"kind": "devices", "query": "zzz qqq", "k": 2})
    names = sorted(p.name for p in (logic._sources() / "devices").glob("*.md"))
    assert out["sources"] == [f"devices/{n}" for n in names[:2]]


def test_an_unknown_kind_says_what_is_allowed():
    assert "grammar, devices" in step.run({"kind": "tools"})["error"]


def test_a_source_without_front_matter_keeps_its_text():
    assert logic.body_of("just text") == ("", "just text")
    assert logic.body_of('---\ntitle: "T"\n---\nbody') == ("T", "body")
