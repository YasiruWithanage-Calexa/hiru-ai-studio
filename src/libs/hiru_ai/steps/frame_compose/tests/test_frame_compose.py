"""frame_compose: the code half of the legacy frame pipeline and inspector, held to the legacy functions."""
from __future__ import annotations

from typing import Any

import pytest
from frame_render.engine import inspect as legacy

from hiru_ai.steps.frame_compose import logic, step

EXPECTED = {"seen": ["Anudi: a woman", "Kasun: a man"], "unseen": ["Father (heard on the phone, not in the place)"],
            "frame": "a stall"}
ANSWERS: list[dict[str, Any]] = [
    {"main_people": 2, "unexpected_person": False, "matches": True, "problems": []},
    {"main_people": 3, "unexpected_person": True, "matches": False, "problems": ["a  b", "c", "d"]},
    {"main_people": "many", "unexpected_person": False, "matches": False, "problems": []},
    {"main_people": 2, "unexpected_person": True, "matches": True, "problems": []},
    {}]


@pytest.mark.parametrize("answer", ANSWERS)
def test_the_vision_chips_are_the_legacy_ones(answer: dict[str, Any]):
    expected = legacy.Expected(**EXPECTED)
    got = legacy.vision_checks(lambda *a: answer, b"x", "image/png", expected)
    assert logic.vision_checks(answer, EXPECTED) == got


def test_no_answer_means_no_chips_and_a_missing_sheet_is_named():
    assert logic.vision_checks(None, EXPECTED) == []
    assert logic.sheet_checks({"a": "Anudi", "b": "Kasun"}, {"a"}) == legacy.sheet_checks(
        {"a": "Anudi", "b": "Kasun"}, {"a"}) == [{"label": "No reference sheet · Kasun", "tone": "advisory"}]


def test_the_looks_op_is_empty_without_looks():
    assert step.run({"op": "looks", "all_looks": [], "scene_looks": [], "episode": 3}) == {"looks": {}}


def test_an_unknown_op_is_refused():
    with pytest.raises(ValueError, match="unknown op"):
        step.run({"op": "nope"})
