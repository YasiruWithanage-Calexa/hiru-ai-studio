from __future__ import annotations

from typing import Any

from hiru_ai.steps.board_settle import step


def out(agent: str, op: dict[str, Any], note: str = "") -> dict[str, Any]:
    return {"agent": agent, "ops": [op], "note": note}


FRAMING = {"op": "set", "shot": 2, "field": "framing", "value": "CU"}
SOUND = {"op": "set", "shot": 1, "field": "sound_mode", "value": "silent"}


def test_a_lone_claim_lands():
    got = step.run({"outputs": [out("cinematography", FRAMING)]})
    assert got == {"ops": [{"agent": "cinematography", "op": FRAMING}], "disagreements": []}


def test_the_owner_wins_a_collision_and_the_rival_is_heard():
    rival = {**SOUND, "value": "ambient"}
    got = step.run({"outputs": [out("cinematography", rival, "keep the street"), out("sound", SOUND, "quiet")]})
    assert [(o["agent"], o["op"]["value"]) for o in got["ops"]] == [("sound", "silent")]  # sound owns sound_mode
    (dis,) = got["disagreements"]
    assert dis["title"] == "Two views on S01 sound mode"
    assert [p["who"] for p in dis["positions"]] == ["Sound", "Cinematography"]


def test_when_the_owner_is_not_among_the_claimants_nobody_lands():
    got = step.run({"outputs": [out("cinematography", SOUND), out("continuity", SOUND)]})
    assert got["ops"] == [] and len(got["disagreements"]) == 1


def test_nothing_proposed_settles_to_nothing():
    assert step.run({"outputs": []}) == {"ops": [], "disagreements": []}
