"""The conductor's rule path (no key, or the model failed) and its model path's clean-up."""
from __future__ import annotations

from director_chat.engine import conductor


def rules(message: str, splits: dict[int, int] | None = None) -> conductor.Plan:
    return conductor.by_rules(message, split_points=splits or {2: 3})


def test_explicit_edits_become_operations():
    assert rules("Make shot 3 six seconds").ops == [{"op": "retime", "shot": 3, "seconds": 6}]
    assert rules("S02 should be 8 sec").ops == [{"op": "retime", "shot": 2, "seconds": 8}]
    assert rules("split shot 2").ops == [{"op": "split", "shot": 2, "at_block": 3}]
    assert rules("split shot 4").ops == []  # nothing to split at
    assert rules("merge shots 3 and 4").ops == [{"op": "merge", "shot": 3}]
    assert rules("merge shots 2 and 5").ops == []  # not neighbours
    assert rules("remove shot 1").ops == [{"op": "remove", "shot": 1}]
    assert rules("shot 1 wide").ops == [{"op": "set", "shot": 1, "field": "framing", "value": "WIDE"}]
    assert rules("make shot 4 a close-up").ops == [{"op": "set", "shot": 4, "field": "framing", "value": "CU"}]
    assert rules("shot 3 silent").ops == [{"op": "set", "shot": 3, "field": "sound_mode", "value": "silent"}]
    assert rules("shot 2 continuous").ops == [{"op": "set_join", "shot": 2, "link": "continuous"}]
    assert rules("envelope 45 seconds").ops == [{"op": "set_envelope", "seconds": 45}]
    plan = rules("Add a reaction of Kamala after shot 2")
    assert plan.lane == "edit" and plan.ops == [{"op": "insert", "after_shot": 2, "description": "Reaction: Kamala",
                                                 "framing": "CU"}]


def test_questions_and_rules_change_nothing():
    plan = rules("Why is the scene so long?")
    assert plan.lane == "chat" and not plan.ops and not plan.memory
    mem = rules("From now on, flashbacks are separate scenes.")
    assert mem.lane == "chat" and mem.memory == ["flashbacks are separate scenes."]


def test_model_plan_is_cleaned():
    answer = {"lane": "bogus", "ops": [{"op": "retime", "shot": 2, "seconds": 6, "field": None}],
              "tasks": [{"agent": "editor", "shots": [1], "instruction": "x"},
                        {"agent": "timing", "shots": [2], "instruction": "tighten"}],
              "memory": ["  ", "Kamala never cries on screen"]}
    plan = conductor.by_model(lambda system, user: answer, plan_text="S01", message="m", history="", memory=[])
    assert plan.lane == "chat"  # an unknown lane is treated as a question
    assert plan.ops == [{"op": "retime", "shot": 2, "seconds": 6}]  # nulls dropped
    assert [t["agent"] for t in plan.tasks] == ["timing"]
    assert plan.memory == ["Kamala never cries on screen"]
