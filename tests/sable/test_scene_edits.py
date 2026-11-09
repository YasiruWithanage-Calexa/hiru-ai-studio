"""Sable edits the open scene (plan/2026-11-09b): the scene-only boundary, shot-list requests and the shot note."""
from __future__ import annotations

from dataclasses import replace

import pytest

from contracts.producer import PersonEdits
from hiru_ai.core import trial
from hiru_ai.core.errors import ToolRefused
from hiru_ai.core.testing import example_ctx, example_of
from hiru_ai.tools.change_propose import tool as propose
from hiru_ai.tools.plan_try import tool as try_tool
from tests.sable.fakes import answer, context, two_models
from tests.sable.test_chat import ctx_with, payload, saved, turn

FRAMING = {"op": "set", "shot": 1, "field": "framing", "value": "CU"}


def sable_ctx(**over):
    return replace(context(), stage_scene_only=True, **over)


# ── phase 0: the boundary ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_card_for_the_open_scene_is_staged():
    ctx = sable_ctx()
    propose.run(propose.Args(summary="Open on a close-up.", ops=[FRAMING], scene="E1S2"), ctx)
    assert len(ctx.ports.staging.staged()) == 1


def test_a_card_for_another_scene_is_refused_with_the_handoff_route():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="open"):
        propose.run(propose.Args(summary="Open on a close-up.", ops=[FRAMING], scene="E1S1"), ctx)
    assert ctx.ports.staging.staged() == []


def test_with_no_scene_open_nothing_is_staged_or_tried():
    ctx = sable_ctx(scene_id=None)
    with pytest.raises(ToolRefused, match="Open the scene first"):
        propose.run(propose.Args(summary="Open on a close-up.", ops=[FRAMING]), ctx)
    with pytest.raises(ToolRefused, match="Open the scene first"):
        try_tool.run(try_tool.Args(ops=[FRAMING]), ctx)


def test_the_director_chat_keeps_its_scene_argument():
    ctx = example_ctx(example_of("change_propose"))
    assert ctx.stage_scene_only is False
    propose.run(propose.Args(summary="Open on a close-up.", ops=[FRAMING], scene="E1S2"), ctx)


def test_the_guard_drops_a_card_for_a_scene_that_is_not_open():
    ctx = ctx_with()
    other = "00000000-0000-4000-8000-0000000000aa"
    ctx.ports.staging.add({"kind": "memory", "rule": "x", "scope": "scene", "scene_id": other})
    with two_models([answer("Done.")], []):
        turn(payload("Remember that."), ctx)
    assert not [b for b in saved(ctx)["blocks"] if b["kind"] == "sable_memory"]
    assert saved(ctx)["meta"]["guard"] == ["card for a scene that is not open"]


# ── phase 1: twelve operations in a card ──────────────────────────────────────────────────────────────────────────────


def test_a_card_may_hold_twelve_operations_and_no_more():
    ops = [{"op": "set", "shot": 1, "field": "framing", "value": "CU"}] * 12
    propose.Args(summary="Twelve.", ops=ops)
    with pytest.raises(ValueError):
        propose.Args(summary="Thirteen.", ops=[*ops, FRAMING])


# ── phase 2: the shot note ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_dop_note_is_staged_as_a_card_with_before_and_after():
    ctx = sable_ctx()
    note = {"op": "dop_note.set", "shot": 1, "value": "The car is a white van."}
    out = propose.run(propose.Args(summary="Make the car a white van.", ops=[note]), ctx)
    (card,) = ctx.ports.staging.staged()
    assert out.staged and card["ops"][0]["op"] == "dop_note.set" and "by" not in card["ops"][0]
    assert card["notes"] == [{"shot": "S01", "before": "", "after": "The car is a white van."}]


def test_the_note_is_still_a_persons_alone_outside_sable():
    ctx = example_ctx(example_of("change_propose"))
    with pytest.raises(ToolRefused, match="person"):
        propose.run(propose.Args(summary="Note.", ops=[{"op": "dop_note.set", "shot": 1, "value": "x"}]), ctx)


@pytest.mark.parametrize("op", [
    {"op": "block.set", "block": 0, "kind": "action", "value": "Kasun frowns."},
    {"op": "canon.add", "shot": 1, "value": "Anudi"},
    {"op": "check.waive", "shot": 1, "value": "timing"},
])
def test_script_cast_and_check_operations_stay_refused_for_sable(op):
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="person"):
        propose.run(propose.Args(summary="No.", ops=[op]), ctx)
    assert ctx.ports.staging.staged() == []


def test_a_note_over_600_characters_is_refused():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="600"):
        propose.run(propose.Args(summary="Long.", ops=[{"op": "dop_note.set", "shot": 1, "value": "a " * 400}]), ctx)


def test_the_trial_never_saves_the_note():
    ctx = sable_ctx()
    tried = trial.run(ctx, None, [propose.views.ToolOp(op="dop_note.set", shot=1, value="A white van.")])
    assert not tried.rejected and "by" not in tried.applied[0]
    assert all(not PersonEdits.of(s).dop_note for s in ctx.ports.scenes.shot_rows)


def test_a_locked_length_is_refused_so_a_persons_choice_is_never_undone_by_a_chat():
    ctx = sable_ctx()
    for row in ctx.ports.scenes.shot_rows:
        if str(row["scene_id"]) == str(ctx.scene_id) and row["number"] == 1:
            row["duration_locked"] = True
    with pytest.raises(ToolRefused, match="Nothing was staged"):
        propose.run(propose.Args(summary="Shorter.", ops=[{"op": "retime", "shot": 1, "seconds": 4}]), ctx)
    assert ctx.ports.staging.staged() == []


# ── phase 4: what the person pointed at reaches the agent ────────────────────────────────────────────────────────────


def test_what_the_person_pointed_at_is_given_to_the_agent_as_mentioned():
    from contracts.sable.events import Mention

    ctx = ctx_with()
    pointed = [Mention(kind="shot", id="x", label="S01", scene="E1S2", text="S01 = shot S01 of E1S2 (open)"),
               Mention(kind="person", id="y", label="Kasun", text="Kasun = person C01 in the canon")]
    with two_models([answer("Fine.")], []) as (base, _):
        turn(payload("make @S01 a close-up", mentions=pointed), ctx)
    sent = str(base.calls[0][-1].content)
    assert "<mentioned>" in sent and "S01 = shot S01 of E1S2 (open)" in sent and "Kasun = person C01" in sent
    with two_models([answer("Fine.")], []) as (base, _):
        turn(payload("no pointing"), ctx_with())
    assert "<mentioned>" not in str(base.calls[0][-1].content)
