"""plan/2026-11-17 §3.7 (phase 0): a Zora or Sable save must not make untouched shots "changed" on the Scene board.

The board marks a panel out of date when its shot's `plan_pin` moves. Zora and Sable both save through
`core.coverage_rows.Saver` (plan/2026-11-13 phase 8; the plan's `jonathan_write` path is no longer the chat's save),
which rewrites the scene's rows in place. These tests apply one change, one insert and one removal through Zora's turn
code with recorded answers and assert that every shot nobody touched keeps its pin, and that undo gives the edited shot
its old pin back (§3.6). Fakes only: no model, no network."""
from __future__ import annotations

from typing import Any

from contracts.board import plan_pin
from tests.zora.rows_world import Recorded, RowsWorld, block_of, data
from tests.zora.test_rows_turn import conductor


def pins(w: RowsWorld) -> dict[str, str]:
    return {str(r["id"]): plan_pin(r) for r in w.scenes.shots(w.scene_id)}


def accepted(w: RowsWorld, out: dict[str, Any]) -> None:
    """A removal or an insert of a must clip comes back as a confirm card: the person accepts it."""
    msg = out["message"][0]
    if any(b.get("kind") == "confirm" for b in msg.get("blocks") or []):
        i, _ = block_of(msg, "confirm")
        assert w.act("accept", message_id=msg["id"], block=i).ok


def test_a_changed_shot_moves_only_its_own_pin() -> None:
    w = RowsWorld()
    before = pins(w)
    first = str(w.scenes.shots(w.scene_id)[0]["id"])
    out = w.turn("Make S01 a wide, 6 seconds.", Recorded())
    assert "plan" in out
    after = pins(w)
    assert after[first] != before[first], "the edited shot's panel is out of date"
    assert {k: v for k, v in after.items() if k != first} == {k: v for k, v in before.items() if k != first}


def test_an_inserted_shot_leaves_every_other_pin_alone() -> None:
    w = RowsWorld()
    before = pins(w)
    m = Recorded(conductor=conductor("edit", [{"op": "insert", "after": "S15", "role": "insert", "size": "INSERT",
                                               "take_s": 4, "first_block": 5, "last_block": 5, "who": ["Dinu"],
                                               "what": "the key in Dinu's palm"}]),
                 authors=[{"notes": "", "asks": [], "variants": [],
                           "ops": [{"op": "set", "shot": "S16", "field": "why",
                                    "value": "The weight lands in a palm."}]}])
    accepted(w, w.turn("Add an insert of the key in Dinu's palm after S15.", m))
    after = pins(w)
    assert len(after) == len(before) + 1
    assert {k: after[k] for k in before} == before, "renumbering never moves a pin"


def test_a_removed_shot_leaves_every_other_pin_alone() -> None:
    w = RowsWorld()
    before = pins(w)
    gone = str(w.scenes.shots(w.scene_id)[7]["id"])
    accepted(w, w.turn("Drop S08.", Recorded()))
    after = pins(w)
    assert gone not in after and len(after) == len(before) - 1
    moved = [k for k in after if after[k] != before[k]]
    # the shots that took over S08's lines changed for real (their plan now performs them); nothing else moved
    rows = {str(r["id"]): r for r in w.scenes.shots(w.scene_id)}
    original = {str(r["id"]): r for r in data()["shots"]}
    assert all(int(rows[k].get("version") or 0) > int(original[k].get("version") or 0) for k in moved), \
        "only a shot the save touched may change its pin"


def test_undo_gives_the_edited_shot_its_old_pin_back() -> None:
    w = RowsWorld()
    before = pins(w)
    w.turn("Make S01 a wide, 6 seconds.", Recorded())
    assert pins(w) != before
    w.turn("undo", Recorded())
    assert pins(w) == before, "undo restores the very plan the panel was painted against (§3.6)"
