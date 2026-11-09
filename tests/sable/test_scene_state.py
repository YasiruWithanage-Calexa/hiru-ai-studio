"""Sable's scene state (plan/2026-11-09b phase 3): the ledger change by code, on the plan/2026-11-09 gold scene."""
from __future__ import annotations

import pytest

from contracts import stagemap as sm
from tests.raphael.test_ledger import BODY, body_scene


def setup():
    scene = body_scene()
    return scene, scene.staging, scene.items()


def test_aruni_dead_from_a_block_makes_marks_from_there_on():
    scene, staging, items = setup()
    made = sm.apply_state(staging, items, [sm.StateMark(who="Aruni", from_block=2, condition="dead")],
                          scene.cast, version=1)
    assert made.by == "person"
    state = sm.state_at(made, items, 2).people["aruni"]
    assert state.condition == "dead" and state.posture == "lying"
    assert sm.state_at(made, items, 0).people["aruni"].condition == ""  # before block 2 nothing changed
    assert sm.state_at(made, items, 0).people["aruni"].posture == "walking"


def test_a_later_mark_cannot_stand_a_body_up():
    scene, staging, items = setup()
    made = sm.apply_state(staging, items, [sm.StateMark(who="Aruni", from_block=1, posture="lying",
                                                        condition="dead")], scene.cast, version=1)
    for block in range(1, len(items)):
        assert sm.state_at(made, items, block).people["aruni"].posture == "lying"


@pytest.mark.parametrize("change,why", [
    (sm.StateMark(who="Dinu", from_block=1, posture="lying"), "not in this scene"),
    (sm.StateMark(who="Aruni", from_block=99, posture="lying"), "no block 99"),
    (sm.StateMark(who="Aruni", from_block=1, posture="floating"), "not a posture"),
    (sm.StateMark(who="Aruni", from_block=1, zone="moon"), "not a spot"),
    (sm.StateMark(who="Aruni", from_block=1), "Nothing to change"),
])
def test_a_change_the_ledger_cannot_take_is_refused_in_words(change, why):
    scene, staging, items = setup()
    with pytest.raises(sm.StateRefused, match=why):
        sm.apply_state(staging, items, [change], scene.cast, version=1)


def test_no_map_no_change():
    scene, _, items = setup()
    with pytest.raises(sm.StateRefused, match="no staging map"):
        sm.apply_state(None, items, [sm.StateMark(who="Aruni", from_block=1, posture="lying")], scene.cast, version=1)


def test_the_blocks_whose_state_changes_are_named():
    scene, staging, items = setup()
    made = sm.apply_state(staging, items, [sm.StateMark(who="Aruni", from_block=2, condition="dead")],
                          scene.cast, version=1)
    assert sm.changed_blocks(staging, made, items, [(0, 1), (1, 2), (2, 3)]) == [2]


def test_the_gold_scene_is_the_one_the_plan_names():
    assert BODY["staging"]["marks"][0]["who"] == "Nimal" and BODY["staging"]["marks"][0]["condition"] == "dead"


# ── the tool ──────────────────────────────────────────────────────────────────────────────────────────────────────────

from dataclasses import replace  # noqa: E402

from hiru_ai.core.errors import ToolRefused  # noqa: E402
from hiru_ai.core.testing import example_ctx, example_of, run_example  # noqa: E402
from hiru_ai.tools.sable.sable_state_propose import tool as propose  # noqa: E402


def test_a_state_change_is_a_card_naming_the_shots_it_touches_and_nothing_else_changes():
    out, ctx = run_example("sable_state_propose")
    (card,) = ctx.ports.staging.staged()
    assert out.staged and card["kind"] == "state" and card["scene"] == "E1S2"
    assert out.changes == ["Kasun: lying, dead, from block 2"] and card["marks"][0]["who"] == "Kasun"
    assert out.touched  # a shot that holds block 2 opens or ends differently
    assert all(r["staging"]["by"] == "model" for r in ctx.ports.scenes.scene_rows if r.get("staging"))  # not rewritten
    assert "Nothing has changed yet" in out.next


def test_a_person_who_is_not_in_the_scene_is_refused_in_words():
    with pytest.raises(ToolRefused, match="not in this scene"):
        run_example("sable_state_propose", {"changes": [{"who": "Nimal", "from_block": 2, "condition": "dead"}]})


def test_no_scene_open_no_state_card():
    ctx = replace(example_ctx(example_of("sable_state_propose")), scene_id=None)
    with pytest.raises(ToolRefused, match="Open the scene first"):
        propose.run(propose.Args(summary="Dead.", changes=[sm.StateMark(who="Kasun", from_block=2,
                                                                          condition="dead")]), ctx)


def test_a_shot_that_still_shows_the_dead_person_alive_is_reported_not_blocked():
    case = example_of("sable_state_propose")
    ctx = example_ctx(case)
    for row in ctx.ports.scenes.shot_rows:
        row["beats"] = [{"action": "Kasun smiles and speaks to her."}]
    out = propose.run(propose.Args(**case["args"]), ctx)
    assert out.staged and any("Kasun" in d and "dead" in d for d in out.in_doubt)
