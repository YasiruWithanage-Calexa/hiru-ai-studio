from __future__ import annotations

from tests.hiru_ai.steps_fixtures import bundle, felt_scene

from hiru_ai.steps.feeling import step
from hiru_ai.steps.feeling.logic import Feeling, performance_missing, want_phrase


def test_a_scene_with_no_reading_or_map_asks_nothing_of_the_shot():
    scene, lines, shots = felt_scene()
    bare = {k: v for k, v in scene.items() if k not in ("reading", "staging")}
    out = step.run(bundle(bare, lines, shots, shot=shots[1]))
    assert out["beat_notes"] == {} and out["turn_beats"] == [] and out["start"] == [] and out["performance"] == ""


def test_the_turn_and_the_held_reaction_land_in_the_beat_they_play_in():
    scene, lines, shots = felt_scene()
    out = step.run(bundle(scene, lines, shots, shot=shots[1]))
    assert out["turn_beats"] == [1, 2]
    assert out["beat_notes"] == {"2": ["Anudi's face receives it, held 1.5 s (the call breaks her joy)"]}
    assert out["person_wants"] == {"Anudi": "wanting to hide it"}
    assert out["start_text"] == "Anudi at the street, facing left, right of frame, holding her phone"


def test_a_wanting_is_phrased_as_one():
    assert want_phrase("to escape") == "wanting to escape" and want_phrase("escape") == "wanting to escape"
    assert want_phrase("") == ""


def test_performance_is_missing_where_the_feeling_turns_and_the_draft_wrote_none():
    feeling = Feeling(turn_beats={0, 1})
    beats = [{"performance": "her smile slips"}, {"performance": "  "}]
    assert performance_missing(feeling, beats, [(0, 3), (3, 6)]) == ["3-6s"]
