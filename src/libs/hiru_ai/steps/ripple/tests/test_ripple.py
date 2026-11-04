from __future__ import annotations

from typing import Any

from tests.services.director_chat.conftest import fixture_scene
from tests.services.production_fixture import PHONE_CANON

from hiru_ai.steps.ripple import step


def review(ops: list[dict[str, Any]]) -> dict[str, Any]:
    scene, lines, shots = fixture_scene(0)
    return step.run({"scene": scene, "lines": lines, "shots": shots, "canon": PHONE_CANON, "ops": ops, "by": "you"})


def dialogue_block() -> int:
    scene, _, _ = fixture_scene(0)
    return next(i for i, b in enumerate(scene["script"]) if b["kind"] == "dialogue")


def test_an_edit_that_changes_nothing_has_nothing_to_check():
    out = review([{"op": "nope"}])
    assert out["impact"] == [] and out["notes"] == [] and out["checked"] == "" and out["rejected"]


def test_a_script_edit_checks_the_shots_around_it_and_asks_continuity_to_look():
    out = review([{"op": "block.set", "block": dialogue_block(), "field": "text", "value": "a different sentence"}])
    assert out["scripted"] and out["impact"] and out["checked"].startswith("Checked S")
    task = out["continuity_task"]
    assert task and task["agent"] == "continuity" and task["shots"] == out["impact"]


def test_a_sound_change_alone_is_not_a_script_change_and_asks_for_no_continuity_pass():
    out = review([{"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}])
    assert not out["scripted"] and out["continuity_task"] is None
