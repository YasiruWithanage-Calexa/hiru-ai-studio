from __future__ import annotations

from typing import Any

from tests.hiru_ai.steps_fixtures import IR, PERSONA, PRODUCTION, felt_scene
from tests.services.production_fixture import PHONE_CANON

from hiru_ai.steps.serialize import step


def prompt(number: int, **extra: Any) -> dict[str, Any]:
    scene, lines, shots = felt_scene()
    return step.run({"production": PRODUCTION, "persona": PERSONA, "canon": PHONE_CANON, "scene": scene,
                     "shots": shots, "lines": lines, "shot_number": number, "ir": IR, **extra})


def test_a_prompt_has_its_fixed_sections_in_order():
    ids = [s["id"] for s in prompt(1)["sections"]]
    assert ids[:2] == ["style", "setting"] and ids[-2:] == ["constraints", "format"]


def test_the_scripts_words_are_placed_verbatim_and_the_check_says_so():
    _, lines, _ = felt_scene()
    out = prompt(1)
    spoken = [seg["sinhala"] for s in out["sections"] for seg in s["segments"] if seg.get("sinhala") is not None]
    assert spoken and spoken[0] == lines[0]["text"]
    assert {"label": "Lines verbatim from the script", "tone": "pass"} in out["checks"]


def test_a_first_frame_opens_the_prompt_only_when_one_is_attached():
    assert "opening" not in [s["id"] for s in prompt(2)["sections"]]
    assert prompt(2, has_frame=True)["sections"][0]["id"] == "opening"


def test_the_free_checks_name_a_turn_with_no_performance_written():
    labels = [c["label"] for c in prompt(2)["checks"]]
    assert any(label.startswith("No performance where the feeling turns") for label in labels)
