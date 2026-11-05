"""The cuts and checks are the legacy engine's, unchanged."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from structure_build.engine import prose as legacy

from hiru_ai.steps.prose_cut import logic, step

HERE = Path(__file__).resolve().parents[1]


DRAMA = (Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "prose" / "three-episode-drama.txt").read_text(
    encoding="utf-8")


def case() -> str:
    return DRAMA


def test_the_episodes_found_and_their_rule_cuts_equal_the_legacy_ones():
    text = case()
    old = [s for s in legacy.sections(text) if legacy.is_script_like(s)]
    new = logic.to_cut(text) or []
    assert [asdict(s) for s in new] == [asdict(s) for s in old] and new
    for a, b in zip(new, old, strict=True):
        assert logic.by_rules(a) == legacy.by_rules(b)
        assert logic.trusted(a, logic.by_rules(a)) == legacy.trusted(b, legacy.by_rules(b))
        assert logic.render(logic.by_rules(a)) == legacy.render(legacy.by_rules(b))


def test_a_cut_that_drops_a_spoken_line_is_not_trusted():
    (first, *_), kept = logic.to_cut(case()) or [], None
    scenes = logic.by_rules(first)
    assert logic.trusted(first, scenes)
    broken = [{**s, "blocks": [b for b in s["blocks"] if b["kind"] != "dialogue"]} for s in scenes]
    assert not logic.trusted(first, broken) and kept is None


def test_assemble_equals_the_legacy_convert_without_a_model():
    text = case()
    todo = logic.to_cut(text) or []
    got = logic.assemble(todo, [(logic.by_rules(s), False, False) for s in todo])
    old = legacy.convert(text, None, [])
    assert old is not None
    assert (got.text, got.scene_seconds, got.episodes, got.by_model, got.fallbacks) == (
        old.text, old.scene_seconds, old.episodes, old.by_model, old.fallbacks)


def test_a_document_with_real_scene_headings_is_left_to_the_parser():
    assert logic.to_cut("INT. KITCHEN - DAY\n\nKAMALA\nCome.\n\nEXT. HARBOUR - DAY\n\nSUNIL\nNets.\n") is None


def test_a_text_without_any_episode_line_is_not_an_error():
    """A plain bible or notes file (role bible/other) has no `Episode n` line. `sections` used to raise ValueError
    (zip strict) and failed the whole build; both engines now return no episodes and the document is left alone."""
    assert legacy.sections("no episodes here") == [] and legacy.convert("no episodes here", None, []) is None
    assert logic.sections("no episodes here") == [] and logic.to_cut("no episodes here") is None
    assert step.run({"op": "to_cut", "text": "no episodes here"}) == {"sections": []}


def test_it_runs_on_its_example():
    example = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    assert len(step.run(example)["sections"]) == 2
