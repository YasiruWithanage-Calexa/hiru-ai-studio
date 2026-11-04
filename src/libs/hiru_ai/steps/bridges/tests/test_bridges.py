from __future__ import annotations

from tests.hiru_ai.steps_fixtures import bundle, felt_scene

from hiru_ai.steps.bridges import step


def test_a_phone_answered_without_a_step_gets_one_implied_block():
    scene, lines, shots = felt_scene()
    out = step.run(bundle(scene, lines, shots))
    (implied,) = [b for b in out["script"] if b.get("implied")]
    assert implied["bridge"] == "answer_phone" and implied["text"] == "Anudi answers the phone."
    assert out["planned"] == [{"before_block": 5, "kind": "answer_phone", "who": "Anudi"}]


def test_running_it_again_adds_nothing_more():
    scene, lines, shots = felt_scene()
    first = step.run(bundle(scene, lines, shots))
    second = step.run(bundle({**scene, "script": first["script"]}, lines, shots))
    assert [b for b in second["script"] if b.get("implied")] == [b for b in first["script"] if b.get("implied")]


def test_a_step_a_person_removed_stays_removed():
    scene, lines, shots = felt_scene()
    script = [dict(b) for b in scene["script"]]
    last = max(i for i, b in enumerate(script) if b["kind"] == "dialogue")
    script[last]["skip_bridges"] = ["answer_phone"]
    out = step.run(bundle({**scene, "script": script}, lines, shots))
    assert not [b for b in out["script"] if b.get("implied")] and out["planned"] == []
