"""Sable edits the open scene (plan/2026-11-09b; plan/2026-11-13 phase 8: through the row kernel, saved in place with
`core.coverage_rows`): the scene-only boundary, shot-list requests, the shot note and the Accept, carried out in
code."""
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from contracts.coverage.scene import Coverage
from contracts.producer import PersonEdits
from contracts.sable.events import SableAction
from hiru_ai.core import row_trial
from hiru_ai.core.errors import ToolRefused
from hiru_ai.tools.sable.sable_shot_change import tool as propose
from hiru_ai.tools.sable.sable_shot_try import tool as try_tool
from tests.sable.fakes import answer, context, two_models
from tests.sable.test_chat import ctx_with, payload, saved, turn

SIZE = {"op": "set", "shot": 1, "field": "size", "value": "CU"}


def sable_ctx(**over):
    return replace(context(), stage_scene_only=True, **over)


def rows_of(ctx) -> list[dict]:
    return sorted((s for s in ctx.ports.scenes.shot_rows if str(s["scene_id"]) == str(ctx.scene_id)),
                  key=lambda s: int(s["number"]))


# ── phase 0: the boundary ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_card_for_the_open_scene_is_staged_with_the_rows_fingerprint():
    ctx = sable_ctx()
    before = [dict(r) for r in rows_of(ctx)]
    out = propose.run(propose.Args(summary="Open on a close-up.", ops=[SIZE], scene="E1S2"), ctx)
    (card,) = ctx.ports.staging.staged()
    assert out.staged and card["engine"] == "rows" and card["made_on"]
    assert card["ops"] == [{"op": SIZE, "by": "author"}]
    assert out.changes == ["S01 · size: MCU → CU"] and card["touched"] == ["S01"]
    assert rows_of(ctx) == before  # nothing saved


def test_a_card_for_another_scene_is_refused_with_the_handoff_route():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="open"):
        propose.run(propose.Args(summary="Open on a close-up.", ops=[SIZE], scene="E1S1"), ctx)
    assert ctx.ports.staging.staged() == []


def test_with_no_scene_open_nothing_is_staged_or_tried():
    ctx = sable_ctx(scene_id=None)
    with pytest.raises(ToolRefused, match="Open the scene first"):
        propose.run(propose.Args(summary="Open on a close-up.", ops=[SIZE]), ctx)
    with pytest.raises(ToolRefused, match="Open the scene first"):
        try_tool.run(try_tool.Args(ops=[SIZE]), ctx)


def test_the_guard_drops_a_card_for_a_scene_that_is_not_open():
    ctx = ctx_with()
    other = "00000000-0000-4000-8000-0000000000aa"
    ctx.ports.staging.add({"kind": "memory", "rule": "x", "scope": "scene", "scene_id": other})
    with two_models([answer("Done.")], []):
        turn(payload("Remember that."), ctx)
    assert not [b for b in saved(ctx)["blocks"] if b["kind"] == "sable_memory"]
    assert saved(ctx)["meta"]["guard"] == ["card for a scene that is not open"]


# ── phase 1: twelve operations in a card; the try tool ────────────────────────────────────────────────────────────────


def test_a_card_may_hold_twelve_operations_and_no_more():
    ops = [SIZE] * 12
    propose.Args(summary="Twelve.", ops=ops)
    with pytest.raises(ValueError):
        propose.Args(summary="Thirteen.", ops=[*ops, SIZE])


def test_the_try_tool_shows_the_shots_with_line_codes_and_tries_without_saving():
    ctx = sable_ctx()
    view = try_tool.run(try_tool.Args(), ctx)
    assert "S01" in view.shots and "S02" in view.shots and "line L1" in view.shots and view.tried == []
    out = try_tool.run(try_tool.Args(ops=[{"op": "retime", "shot": 1, "take_s": 8}, {"op": "retime", "shot": 9,
                                                                                   "take_s": 4}]), ctx)
    assert out.applied == 1 and out.refused == 1 and out.tried[1]["why"] == "there is no shot 9"
    assert int(rows_of(ctx)[0]["duration_s"]) == 6 and ctx.ports.staging.staged() == []


def test_a_risky_change_says_why_a_person_must_ok_it():
    ctx = sable_ctx()
    out = try_tool.run(try_tool.Args(ops=[{"op": "remove", "shot": 2}]), ctx)
    assert any("performs L5" in r for r in out.needs_ok)
    assert any("L5" in p for p in out.new_problems)  # the father's line has no clip left


def test_any_refused_operation_stages_nothing_and_says_why():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused) as refused:
        propose.run(propose.Args(summary="Two.", ops=[SIZE, {"op": "set", "shot": 9, "field": "size",
                                                             "value": "CU"}]), ctx)
    assert "1 of 2" in str(refused.value) and "Nothing was staged" in str(refused.value)
    assert ctx.ports.staging.staged() == []


# ── phase 2: the shot note ────────────────────────────────────────────────────────────────────────────────────────────


def test_a_dop_note_is_staged_as_a_card_and_never_saved_by_the_trial():
    ctx = sable_ctx()
    note = {"op": "note", "shot": 1, "value": "The car is a white van."}
    out = propose.run(propose.Args(summary="Make the car a white van.", ops=[note]), ctx)
    (card,) = ctx.ports.staging.staged()
    assert card["ops"][0]["op"]["op"] == "note" and out.changes == ["S01 · DoP note: - → The car is a white van."]
    assert all(not PersonEdits.of(s).dop_note for s in ctx.ports.scenes.shot_rows)


def test_a_note_over_600_characters_is_refused():
    ctx = sable_ctx()
    with pytest.raises(ToolRefused, match="600"):
        propose.run(propose.Args(summary="Long.", ops=[{"op": "note", "shot": 1, "value": "a " * 400}]), ctx)


def test_a_locked_length_is_refused_so_a_persons_choice_is_never_undone_by_a_chat():
    ctx = sable_ctx()
    rows_of(ctx)[0]["duration_locked"] = True
    with pytest.raises(ToolRefused, match="locked"):
        propose.run(propose.Args(summary="Shorter.", ops=[{"op": "retime", "shot": 1, "take_s": 4}]), ctx)
    assert ctx.ports.staging.staged() == []


# ── phase 8: Accept, saved in place ─────────────────────────────────────────────────────────────────────────────────


def _accept(ctx, card):
    """The API's Accept: the function's `apply` on the same rows (a director port and undo stack for the run)."""
    from hiru_ai.core.fakes import FakeDirector, FakeRevisions
    from hiru_ai.systems.sable.sable_chat import graph

    scene = next(s for s in ctx.ports.scenes.scene_rows if str(s["id"]) == str(ctx.scene_id))
    if ctx.ports.director is None:
        ctx = replace(ctx, ports=replace(ctx.ports, director=FakeDirector(scene), revisions=FakeRevisions()))
    req = SableAction(production_id=ctx.production_id, scene_id=ctx.scene_id,
                      actor_user_id=UUID("00000000-0000-4000-8000-000000000001"), ops=card["ops"],
                      made_on=card["made_on"], summary=card["summary"])
    return graph.act(req, ctx)


def test_an_accepted_card_is_saved_in_place_and_the_note_moves_the_version():
    ctx = sable_ctx()
    propose.run(propose.Args(summary="A white van; open close.",
                             ops=[{"op": "note", "shot": 1, "value": "The car is a white van."}, SIZE]), ctx)
    (card,) = ctx.ports.staging.staged()
    first = dict(rows_of(ctx)[0])
    out = _accept(ctx, card)
    assert out.ok, out.text
    after = rows_of(ctx)[0]
    assert after["id"] == first["id"] and after["framing"] == "CU"
    assert PersonEdits.of(after).dop_note == "The car is a white van."
    assert int(after["version"]) == int(first.get("version") or 1) + 1
    assert "size" not in (after.get("person_edits") or {}).get("zora_locks", [])  # a model's change is not locked


def test_a_card_made_on_other_rows_is_refused_and_nothing_is_saved():
    ctx = sable_ctx()
    propose.run(propose.Args(summary="Open close.", ops=[SIZE]), ctx)
    (card,) = ctx.ports.staging.staged()
    rows_of(ctx)[1]["framing"] = "WIDE"  # someone changed the shots meanwhile
    out = _accept(ctx, card)
    assert not out.ok and "changed since" in out.text and rows_of(ctx)[0]["framing"] == "MCU"


def test_an_apply_never_writes_as_a_person_whatever_the_card_says():
    ctx = sable_ctx()
    rows_of(ctx)[0]["person_edits"] = {"zora_locks": ["size"]}
    scene = next(s for s in ctx.ports.scenes.scene_rows if str(s["id"]) == str(ctx.scene_id))
    cov = row_trial.coverage(ctx, ctx.ports.scenes, scene)
    assert isinstance(cov, Coverage)
    card = {"ops": [{"op": SIZE, "by": "person"}], "made_on": cov.fingerprint(), "summary": "Sneaky."}
    out = _accept(ctx, card)
    assert not out.ok and "locked" in out.text and rows_of(ctx)[0]["framing"] == "MCU"


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
