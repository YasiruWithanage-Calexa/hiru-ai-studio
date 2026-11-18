"""findings/issues/2026-11-17/ZORA-CHAT.md, held by code (fakes and recorded answers only: no model, no network).

    C1   an operation's field is one of ITS fields (the schema, the kernel, Sable's RowOp)
    C2   a value already there is skipped, never "couldn't apply"
    C4/5 the scene board: what it shows, the Update board card after a save, the board lane
    C6/7 the hands: a hands card the person accepts writes the state ledger; text that names the other hand is reported
    C8   the models' own slips never reach the person; a reply that claims a limit no fact backs is cut
    C9   a size is `framing`, not `camera`: a task that does not give it cannot change it
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from contracts import reading, sceneplan
from contracts import stagemap as sm
from contracts.board import plan_pin
from contracts.coverage import scene as coverage_scene
from contracts.zora import wire
from hiru_ai.core import row_trial
from hiru_ai.core.context import RunContext
from hiru_ai.core.coverage_rows import read as read_world
from hiru_ai.core.fakes import FakeFrames
from hiru_ai.steps.coverage_kernel.logic import SET_FIELDS, Kernel
from hiru_ai.systems.zora.zora_chat import board_view, hands
from hiru_ai.systems.zora.zora_chat.turn import fence, guard
from tests.zora.rows_world import Recorded, RowsWorld, block_of, scene


def staged(w: RowsWorld) -> RowsWorld:
    """The lab's copy of the scene stores its staging map with no `basis` (the stager writes one): stamp it, so the map
    reads as written for this script."""
    row = w.scenes.scene_rows[0]
    row["staging"]["basis"] = reading.basis(sceneplan.scene_items(row, w.scenes.lines(w.scene_id)))
    return w


def conductor(lane: str, ops: list[dict] | None = None, tasks: list[dict] | None = None,
              hands_: list[dict] | None = None) -> dict:
    return {"lane": lane, "confidence": 0.9, "ops": ops or [], "tasks": tasks or [], "variants": 0, "cannot": None,
            "memory": "", "hands": hands_ or []}


# ── C1: the shapes ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_wire_repeats_the_coverage_lists_exactly() -> None:
    for name in ("SIZES", "TAKES", "CINE", "IR_TEXT", "IR_JSON", "SOUND_MODES", "PRIORITIES"):
        assert tuple(getattr(wire, name)) == tuple(getattr(coverage_scene, name)), name
    assert wire.SET_FIELDS == SET_FIELDS == row_trial.SET_FIELDS


def test_each_operation_has_only_its_own_fields_and_set_names_no_made_up_field() -> None:
    shapes = {b["properties"]["op"]["enum"][0]: b for b in wire.op_schema()["anyOf"]}
    assert set(shapes) == set(wire.OP_NAMES)
    assert all(b["additionalProperties"] is False and b["required"] == list(b["properties"]) for b in shapes.values())
    fields = shapes["set"]["properties"]["field"]["enum"]
    assert not {"who", "what", "role", "first_block", "on screen"} & set(fields)
    assert set(shapes["set"]["properties"]) == {"op", "shot", "field", "value"}
    assert {"who", "first_block"} <= set(shapes["insert"]["properties"])
    conductor_set = next(b for b in wire.conductor_schema()["properties"]["ops"]["items"]["anyOf"]
                         if b["properties"]["op"]["enum"] == ["set"])
    assert conductor_set["properties"]["field"]["enum"] == list(wire.CONDUCTOR_SET_FIELDS)


def test_sable_cannot_send_a_field_set_does_not_have() -> None:
    with pytest.raises(ValueError, match="set's field is one of"):
        row_trial.RowOp(op="set", shot=8, field="who", value="Anudi")
    with pytest.raises(ValueError, match="sound's field is one of"):
        row_trial.RowOp(op="sound", shot=8, field="on screen", value="x")
    assert row_trial.RowOp(op="set", shot=8, field="sees", value="x").as_op()["field"] == "sees"


# ── C2: a value already there ─────────────────────────────────────────────────────────────────────────────────────


def test_a_value_already_there_is_skipped_not_refused() -> None:
    cov = scene()
    size = cov.clips[0].size
    res = Kernel(cov).apply([{"op": "set", "shot": "S01", "field": "size", "value": size},
                             {"op": "retime", "shot": "S01", "take_s": cov.clips[0].take_s}], by="author")
    assert not res.applied and not res.rejected and len(res.skipped) == 2
    bad = Kernel(cov).apply([{"op": "set", "shot": "S01", "field": "who", "value": "Dinu"}], by="author")
    assert bad.rejected and "not a field set writes" in bad.rejected[0]["reason"]


# ── C8, C9: slips stay out of sight; the fence ────────────────────────────────────────────────────────────────────


def test_a_size_needs_framing_and_a_shot_outside_the_task_is_refused() -> None:
    cov = scene()
    tasks = [{"writes": ["picture", "camera"], "scope": [cov.clips[5].h], "instruction": "show the phone"}]
    kept, out = fence([{"op": "set", "shot": "S06", "field": "size", "value": "MCU"},
                       {"op": "set", "shot": "S06", "field": "sees", "value": "x"},
                       {"op": "set", "shot": "S05", "field": "sees", "value": "y"}], tasks, cov)
    assert [o["field"] for o in kept] == ["sees"] and kept[0]["shot"] == "S06"
    assert len(out) == 2 and any("(framing)" in x for x in out)


def test_the_authors_own_slips_never_reach_the_couldnt_apply_list() -> None:
    w = RowsWorld()
    m = Recorded(conductor=conductor("craft", tasks=[{"writes": ["picture"], "shots": [8], "instruction": "warmer"}]),
                 authors=[{"notes": "", "asks": [], "variants": [],
                           "ops": [{"op": "set", "shot": "S08", "field": "who", "value": "Dinu"},
                                   {"op": "set", "shot": "S08", "field": "size", "value": "MCU"},
                                   {"op": "set", "shot": "S08", "field": "why", "value": "Warmth lands on Dinu."}]}],
                 reply="I warmed S08.")
    out = w.turn("Make S08 warmer.", m)
    ledger = out["ops"][0]
    assert ledger["refused"] == [] and any(c["where"] == "S08" for c in ledger["changes"])
    assert w.cov().clips[7].size != "MCU" or scene().clips[7].size == "MCU"  # the size nobody asked for is not there


def test_a_reply_that_claims_a_limit_no_fact_backs_is_cut() -> None:
    text = ("I turned the phone toward camera in S06. I couldn't change S08 or S09 here, those on-screen fields "
            "aren't editable. I kept the line as written and did not change it.")
    kept, cut = guard(text, card=False, proposals=False, limits=False)
    assert "couldn't" not in kept and "did not change it" in kept and cut
    assert guard(text, card=False, proposals=False, limits=True)[0] == text


# ── C4, C5: the scene board ───────────────────────────────────────────────────────────────────────────────────────


class BoardWorld(RowsWorld):
    """The scene with a painted, approved board whose panels show every shot as it is now."""

    def __init__(self) -> None:
        super().__init__()
        self.frames = FakeFrames()
        shots = self.scenes.shots(self.scene_id)
        cells = [{"shot_id": str(s["id"]), "number": int(s["number"]), "kind": "painted", "path": "p.png",
                  "pin": plan_pin(s)} for s in shots]
        self.frames.board_rows["b1"] = {"id": "b1", "scene_id": self.scene_id, "version": 1, "part": 1,
                                        "status": "done", "cells": cells, "approved_at": "2026-11-17"}

    def ctx(self) -> RunContext:
        base = super().ctx()
        return replace(base, ports=replace(base.ports, frames=self.frames))


def test_the_board_reads_up_to_date_then_names_the_shots_a_change_left_behind() -> None:
    w = BoardWorld()
    world = read_world(w.ctx(), w.ctx().production_id, w.scene_id)  # type: ignore[arg-type]
    assert not isinstance(world, str)
    view = board_view.view(w.ctx(), w.scene_id, world.shot_rows)
    assert view.exists and view.updatable and not view.out_of_date()
    assert "up to date" in view.sentence()

    out = w.turn("Make S01 a wide, 6 seconds.", Recorded(reply="I opened S01 up."))
    msg = out["message"][0]
    _, card = block_of(msg, "board")
    assert card["shots"] == ["S01"] and card["shot_ids"] == [str(w.scenes.shots(w.scene_id)[0]["id"])]


def test_asking_about_the_board_changes_nothing_and_offers_update_board_for_the_named_shots() -> None:
    w = BoardWorld()
    before = [dict(r) for r in w.scenes.shots(w.scene_id)]
    m = Recorded(conductor=conductor("board"), reply="The board is up to date; press Update board for S06.")
    out = w.turn("Repaint S06 on the board.", m)
    assert m.roles() == ["conductor", "reply"] and "plan" not in out
    assert w.scenes.shots(w.scene_id) == before
    _, card = block_of(out["message"][0], "board")
    assert card["shots"] == ["S06"]
    facts = next(c[1] for c in m.calls if c[0] == "reply")["facts"]
    assert any("SCENE BOARD" in f and "never paints" in f for f in facts)


def test_without_a_board_port_nothing_about_the_board_is_said() -> None:
    w = RowsWorld()
    out = w.turn("Make S01 a wide, 6 seconds.", Recorded())
    assert not any(b.get("kind") == "board" for b in out["message"][0]["blocks"])


# ── C6, C7: the hands ─────────────────────────────────────────────────────────────────────────────────────────────


def test_a_hand_the_person_names_is_a_card_and_accept_writes_the_ledger() -> None:
    w = staged(RowsWorld())
    m = Recorded(conductor=conductor("edit", hands_=[{"who": "Dinu", "thing": "the C-17 key", "hand": "right",
                                                      "from_block": 5}]),
                 reply="That moves the key to Dinu's right hand once you accept.")
    out = w.turn("Dinu holds the key in his right hand.", m)
    msg = out["message"][0]
    i, card = block_of(msg, "confirm")
    assert card["fix"] == "hands" and card["marks"][0]["right_hand"] == "the C-17 key"
    assert "S14" in card["touched"]
    assert w.scenes.scene_rows[0]["staging"]["marks"][-1]["right_hand"] == ""  # nothing saved before Accept
    versions = {str(r["id"]): int(r.get("version") or 1) for r in w.scenes.shots(w.scene_id)}

    done = w.act("accept", message_id=msg["id"], block=i)
    assert done.ok
    staging = sm.SceneStaging.model_validate(w.scenes.scene_rows[0]["staging"])
    assert staging.by == "person"
    assert any(mk.who == "Dinu" and mk.block == 5 and "key" in mk.right_hand for mk in staging.marks)
    moved = [r for r in w.scenes.shots(w.scene_id) if int(r.get("version") or 1) != versions[str(r["id"])]]
    assert moved and all(int(r["block_end"]) > 5 for r in moved)


def test_a_hand_on_a_person_not_in_the_scene_is_said_plainly_and_nothing_waits() -> None:
    w = staged(RowsWorld())
    m = Recorded(conductor=conductor("edit", hands_=[{"who": "Anudi", "thing": "the phone", "hand": "left",
                                                      "from_block": 2}]))
    out = w.turn("Anudi holds the phone in her left hand.", m)
    assert not any(b.get("kind") == "confirm" for b in out["message"][0]["blocks"])
    facts = next(c[1] for c in m.calls if c[0] == "reply")["facts"]
    assert any("the hand change: Anudi is not in this scene" in f for f in facts)


def test_text_that_puts_a_held_thing_in_the_other_hand_is_reported() -> None:
    w = staged(RowsWorld())
    row = w.scenes.scene_rows[0]
    row["staging"]["marks"][-1]["right_hand"] = "C-17 key"
    world = read_world(w.ctx(), w.ctx().production_id, w.scene_id)  # type: ignore[arg-type]
    assert not isinstance(world, str)
    cov = world.cov.copy()
    clip = cov.clips[15]  # S16, Dinu over b5
    clip.sees = "Dinu turns the C-17 key over in his left hand."
    said = hands.disagree(world, cov, [clip.h])
    assert said and "left hand" in said[0] and "right hand" in said[0]
    clip.sees = "Dinu turns the C-17 key over in his right hand."
    assert hands.disagree(world, cov, [clip.h]) == []


def test_the_ledger_moves_a_thing_between_hands_and_carries_it_on() -> None:
    from tests.raphael.test_ledger import body_scene

    s = body_scene()
    made = sm.apply_state(s.staging, s.items(), [sm.StateMark(who="Aruni", from_block=1, left_hand="the phone")],
                          s.cast, version=1)
    later = next(mk for mk in made.marks if mk.who == "Aruni" and mk.block == 2)
    assert "phone" in later.left_hand and later.right_hand == ""  # the later mark's phone moved hand too
    assert sm.state_at(made, s.items(), 2).people["aruni"].hand_of("phone") == "left"
