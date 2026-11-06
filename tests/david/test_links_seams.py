"""Which scenes carry on from the one before (§4.3) and the join between two scenes (§4.3, §7)."""
from __future__ import annotations

from typing import Any

import pytest

from contracts.david import links, seams
from contracts.david.wire import DavidWire, EndStateW
from hiru_ai.core import parts
from tests.david import gold


def row(n: int, *, episode: str = "e1", place: str = "loc-1", time: str = "DAY") -> dict[str, Any]:
    return {"id": f"{episode}-{n}", "episode_id": episode, "episode_number": int(episode[1:]), "number": n,
            "location_id": place, "time_of_day": time}


def run_links(scenes: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return parts.step("david_links", "step").run({"scenes": scenes, **kw})  # type: ignore[no-any-return]


# ── david_links ──────────────────────────────────────────────────────────────────────────────


def test_a_scene_carries_on_when_it_is_in_the_same_place_and_its_time_says_so():
    scenes = [row(1), row(2, time="CONTINUOUS"), row(3, time="MOMENTS LATER"), row(4, time="SAME TIME", place="loc-2"),
              row(5, time="DAY")]
    out = run_links(scenes)
    assert out["links"] == {"e1-1": "", "e1-2": "continuous", "e1-3": "continuous", "e1-4": "", "e1-5": ""}
    assert out["chains"] == [["e1-1", "e1-2", "e1-3"], ["e1-4"], ["e1-5"]]


def test_a_chain_never_crosses_an_episode_boundary():
    out = run_links([row(1, episode="e1"), row(1, episode="e2", time="CONTINUOUS")])
    assert out["links"] == {"e1-1": "", "e2-1": ""} and len(out["chains"]) == 2


def test_in_episode_order_every_pair_is_linked_and_one_that_is_not_continuous_carries_only_looks_and_what_people_keep():
    out = run_links([row(1), row(2, place="loc-2"), row(3, time="CONTINUOUS", place="loc-2"), row(4)], order="episode")
    assert out["links"] == {"e1-1": "", "e1-2": "carry", "e1-3": "continuous", "e1-4": "carry"}
    assert out["chains"] == [["e1-1", "e1-2", "e1-3", "e1-4"]]


def test_two_episodes_in_episode_order_are_two_chains_that_run_at_once():
    scenes = [row(1, episode="e1"), row(2, episode="e1"), row(1, episode="e2"), row(2, episode="e2")]
    assert run_links(scenes, order="episode")["chains"] == [["e1-1", "e1-2"], ["e2-1", "e2-2"]]


def test_a_person_can_link_or_unlink_a_pair_and_that_wins():
    scenes = [row(1), row(2, time="CONTINUOUS"), row(3)]
    out = run_links(scenes, overrides={"e1-2": "none", "e1-3": "continuous"})
    assert out["links"] == {"e1-1": "", "e1-2": "", "e1-3": "continuous"}
    assert links.link_of(None, row(1)) == "" and links.link_of(row(1), row(2), override="carry") == "carry"


# ── david_seams ──────────────────────────────────────────────────────────────────────────────


def second_scene() -> DavidWire:
    """The phone call as a second scene that opens where the first ended: Anudi on the path with her bag."""
    plan = gold.phone_call().model_dump()
    marks = plan["staging"]["marks"]
    marks[0]["zone"] = "path"
    marks[0]["holding"] = "her bag"
    plan["shots"][0]["ir"]["subjects"] = [{"id": "C01", "description": "Anudi in a pale green kurta", "action": "walks",
                                           "position": "on the path"}]
    plan["shots"][0]["ir"]["lighting"] = "Low golden sun from the left"
    return DavidWire.model_validate(plan)


def seam(link: str, after: DavidWire, start: EndStateW | None = None) -> list[Any]:
    before = gold.phone_call().end_state
    out = parts.step("david_seams", "step").run({"before": before.model_dump(), "link": link,
                                                 "start": (start or before).model_dump(), "after": after.model_dump(),
                                                 "number": 2})
    return out["problems"]  # type: ignore[no-any-return]


def test_a_scene_that_opens_where_the_one_before_ended_has_no_seam():
    assert seam("continuous", second_scene()) == []


def test_a_person_in_another_place_without_a_move_is_found_and_can_be_repaired():
    found = seam("continuous", gold.phone_call())  # it opens at the bench; scene 1 ended on the path
    assert any("Anudi" in p["sentence"] and "path" in p["sentence"] and p["fix"] == "repair" for p in found)
    assert any("holding" in p["sentence"] for p in found)  # and her bag is gone from her hands


def test_other_clothes_across_a_seam_with_no_change_shown_are_found_for_continuous_and_carry_pairs():
    plan = second_scene()
    plan.shots[0].ir["subjects"][0]["description"] = "Anudi in a red sari with gold bangles"
    assert any("Anudi" in p["sentence"] and "red sari" in p["sentence"] for p in seam("continuous", plan))
    carry = seam("carry", plan)
    assert any("red sari" in p["sentence"] for p in carry) and not any("holding" in p["sentence"] for p in carry)


def test_other_light_across_a_continuous_seam_is_found():
    plan = second_scene()
    plan.shots[0].ir["lighting"] = "Cold blue moonlight, hard shadows"
    assert any("moonlight" in p["sentence"] for p in seam("continuous", plan))


def test_an_unlinked_pair_is_only_compared_on_looks_and_only_reported():
    canon = gold.phone_call().end_state.model_copy(deep=True)
    canon.people[0].look = "a red sari with gold bangles"
    found = seam("", gold.phone_call(), start=canon)
    assert [p["fix"] for p in found] == ["report"] and "red sari" in found[0]["sentence"]
    assert not any("path" in p["sentence"] for p in found)  # place is not compared across an unlinked pair


@pytest.mark.parametrize(("a", "b", "same"), [("pale green kurta", "a green kurta, pale", True),
                                              ("pale green kurta", "red sari with gold bangles", False),
                                              ("", "anything", True)])
def test_two_descriptions_of_a_look_are_compared_loosely(a: str, b: str, same: bool):
    assert seams.similar(a, b) is same


def test_a_look_change_inside_a_scene_is_worked_out_by_code_and_recorded_once():
    start = gold.phone_call().end_state.model_copy(deep=True)
    end = start.model_copy(deep=True)
    end.people[0].look = "a torn red sari, mud on the hem"
    out = parts.step("david_seams", "step").run({"start": start.model_dump(), "end": end.model_dump(), "number": 3})
    assert [c["who"] for c in out["look_changes"]] == ["Anudi"] and out["look_changes"][0]["scene"] == 3
    assert out["look_changes"][0]["before"] == "pale green kurta" and "torn red sari" in out["look_changes"][0]["after"]
    same = parts.step("david_seams", "step").run({"start": start.model_dump(), "end": start.model_dump(), "number": 3})
    assert same["look_changes"] == []
