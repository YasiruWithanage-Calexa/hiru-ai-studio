"""The wire shapes and what moves shots about (plan/2026-11-05e §5): the patch the repairer answers with,
renumbering, and the
JSON schema the author is held to."""
from __future__ import annotations

from typing import Any

from contracts.david.stored import Removed, StoredPlan
from contracts.david.wire import DavidWire, PatchWire
from hiru_ai.agents.david.david_author import agent
from hiru_ai.steps.serialize.schema import get_schema
from tests.david import gold


def patch(*replaces: dict[str, Any], staging: list | None = None, end_state: list | None = None) -> PatchWire:
    return PatchWire.model_validate({"replaces": list(replaces), "staging": staging or [],
                                     "end_state": end_state or []})


def shot(n: int, **kw: Any) -> dict[str, Any]:
    return gold.shot(n, kw.pop("blocks", []), kw.pop("size", "MS"), kw.pop("take", 4), kw.pop("why", "a shot"), **kw)


def test_a_patch_replaces_a_run_of_shots_and_the_rest_are_renumbered_with_their_additions():
    plan = gold.phone_call()
    mended = plan.patched(patch({"replace_from": 2, "replace_to": 3, "shots": [shot(1, blocks=[1, 2], lines=["L1"])],
                                 "added": []}))
    assert [s.n for s in mended.shots] == list(range(1, 10)) and mended.shots[1].blocks == [1, 2]
    assert mended.shots[2].blocks == [3]  # what followed the run moved up
    assert mended.added[0].shot == 9 and mended.shots[8].blocks == []  # the reaction shot is still last, still listed


def test_a_patch_can_insert_without_removing_and_a_removed_shot_takes_its_additions_with_it():
    plan = gold.phone_call()
    inserted = plan.patched(patch({"replace_from": 3, "replace_to": 2, "shots": [shot(1, blocks=[])], "added": [
        {"shot": 1, "kind": "atmosphere", "what": "the lake", "who": [], "object": ""}]}))
    assert len(inserted.shots) == 11 and inserted.shots[2].blocks == []
    assert sorted(a.shot for a in inserted.added) == [3, 11]
    gone = plan.patched(patch({"replace_from": 10, "replace_to": 10, "shots": [], "added": []}))
    assert len(gone.shots) == 9 and gone.added == []


def test_a_patch_can_replace_the_staging_and_the_end_state_and_nothing_else_changes():
    plan = gold.phone_call()
    staging = plan.staging.model_copy(update={"zones": ["a", "b"], "marks": []})
    ends = plan.end_state.model_copy(update={"time": "dusk"})
    out = plan.patched(patch(staging=[staging.model_dump()], end_state=[ends.model_dump()]))
    assert out.staging.zones == ["a", "b"] and out.end_state.time == "dusk" and out.shots == plan.shots
    assert plan.patched(patch()) == plan


def test_renumbering_keeps_list_order_when_the_models_numbers_repeat():
    plan = gold.phone_call()
    shots = [s.model_copy(update={"n": 1}) for s in plan.shots]
    out = DavidWire.model_validate({**plan.model_dump(), "shots": [s.model_dump() for s in shots]}).renumbered()
    assert [s.n for s in out.shots] == list(range(1, 11))


def test_the_authors_schema_is_one_flat_strict_tree_with_the_clip_schema_in_place_of_the_free_ir():
    schema = agent.output_schema()
    text = str(schema)
    assert "$ref" not in text and "$defs" not in text and schema["title"] == "david_plan"
    shot_props = schema["properties"]["shots"]["items"]["properties"]
    clip = get_schema().required_structure
    assert list(shot_props["ir"]["properties"]) == list(clip) and shot_props["ir"]["additionalProperties"] is False
    assert shot_props["take_s"]["enum"] == [4, 6, 8] and "WIDE" in shot_props["size"]["enum"]
    assert shot_props["ir"]["required"] == list(clip)  # strict mode: every property is required


def test_a_stored_plan_round_trips_through_the_json_the_scene_keeps():
    stored = StoredPlan(plan=gold.phone_call(), end_state=gold.phone_call().end_state,
                        removed=[Removed(kind="reaction", after_block=9, what="x")])
    loaded = StoredPlan.load(stored.data())
    assert loaded == stored and StoredPlan.load({}) is None and StoredPlan.load({"planner": "adam"}) is None
    assert StoredPlan.load({"planner": "david", "plan": "garbage"}) is None
