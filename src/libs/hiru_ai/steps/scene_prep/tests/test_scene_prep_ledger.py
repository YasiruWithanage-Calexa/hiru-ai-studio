"""The stager's state ledger through `make_staging` (plan/2026-11-09 phase 2): the new fields round-trip, a junk
posture is dropped, a failed call is no map, and a current or a person's map is kept with no call."""

from __future__ import annotations

from typing import Any

from contracts import stagemap as sm
from contracts.shotplan import Item
from hiru_ai.agents.stager.schema import Output
from hiru_ai.steps.scene_prep import logic

ITEMS = [
    Item(0, "action", "Kasun stands beside his three-wheeler.", screen="act"),
    Item(1, "action", "Anudi drops her phone.", screen="act"),
    Item(2, "dialogue", "Miss!", "Kasun", None, "", "l1"),
]
REPLY: dict[str, Any] = {
    "zones": ["stall counter", "pavement"],
    "marks": [
        {"block": 0, "who": "Kasun", "zone": "stall counter", "facing": "right", "frame_side": "left",
         "holding": "", "posture": "standing", "left_hand": "", "right_hand": "", "condition": "", "wearing": ""},
        {"block": 1, "who": "Anudi", "zone": "pavement", "facing": "left", "frame_side": "right",
         "holding": "umbrella", "posture": "walking", "left_hand": "", "right_hand": "umbrella", "condition": "soaked",
         "wearing": "jacket off"},
    ],
    "props": [{"block": 1, "prop": "phone", "where": "on the ground", "state": ""}],
}


def test_the_new_fields_round_trip_from_the_agents_output_to_the_map():
    answer = Output.model_validate(REPLY).model_dump()
    made = logic.make_staging(lambda items: answer, ITEMS, ["Kasun", "Anudi"], version=1)
    assert made is not None and made.by == "model" and made.written_at
    anudi = next(m for m in made.marks if m.who == "Anudi")
    assert (anudi.posture, anudi.right_hand, anudi.condition, anudi.wearing) == ("walking", "umbrella", "soaked",
                                                                                 "jacket off")
    assert [(p.block, p.prop, p.where) for p in made.props] == [(1, "phone", "on the ground")]


def test_a_junk_posture_is_dropped():
    junk = {**REPLY, "marks": [{**REPLY["marks"][0], "posture": "hovering"}]}
    made = logic.make_staging(lambda items: junk, ITEMS, ["Kasun"], version=1)
    assert made is not None and made.marks[0].posture == ""


def test_a_failed_call_is_no_map():
    def boom(items: list[Item]) -> dict[str, Any]:
        raise RuntimeError("down")

    assert logic.make_staging(boom, ITEMS, ["Kasun"], version=1) is None


def test_a_current_or_a_persons_map_is_kept_without_a_call():
    calls: list[int] = []

    def ask(items: list[Item]) -> dict[str, Any]:
        calls.append(1)
        return REPLY

    current = sm.validate(REPLY, ITEMS, ["Kasun", "Anudi"], version=1, by="model")
    scene = {"script_version": 1, "staging": current.model_dump()}
    kept, made = logic.staging_for(scene, ITEMS, ask, ["Kasun", "Anudi"])
    assert kept is not None and not made and not calls
    stale = {"script_version": 2, "staging": current.model_dump()}
    _, made = logic.staging_for(stale, ITEMS, ask, ["Kasun", "Anudi"])
    assert made and calls == [1]
    person = {"script_version": 2, "staging": {**current.model_dump(), "by": "person"}}
    kept, made = logic.staging_for(person, ITEMS, ask, ["Kasun", "Anudi"])
    assert kept is not None and kept.by == "person" and not made and calls == [1]
