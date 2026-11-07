"""Tests that live with the zora_save step (ADR 0006). The example is the planner's own write example with S03 put on
an 85 and that lens locked."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from hiru_ai.steps.zora.zora_save import logic, step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_edit_is_stored_through_the_planners_write_path_and_every_shot_keeps_its_id():
    out = step.run(copy.deepcopy(EXAMPLE))
    assert [s["id"] for s in out["shots"]] == EXAMPLE["old_ids"] and out["removed"] == []
    assert out["fields"]["jonathan"]["plan"]["shots"][2]["lens"] == "85mm"
    assert out["fields"]["jonathan"]["person"] == {"locked": ["S03.lens"], "settled": []}
    bound = {ln["shot_id"] for ln in out["lines"] if ln["shot_id"]}
    assert bound <= set(EXAMPLE["old_ids"])
    # what the planner keeps besides the plan is left exactly as it was
    for key in ("link", "start", "removed", "line_ids", "previous", "input_hash"):
        assert out["stored"][key] == EXAMPLE["stored"][key]


def test_a_new_shot_keeps_its_fresh_id_and_a_gone_one_is_named():
    rows = [{"id": "new1", "number": 1}, {"id": "new2", "number": 2}]
    shots, lines, gone = logic.keep_ids(rows, [{"id": "L", "shot_id": "new1"}], ["old1", "old2"], ["h2", "n1"])
    assert [s["id"] for s in shots] == ["old2", "new2"] and lines[0]["shot_id"] == "old2" and gone == ["old1"]


def test_an_approved_scene_is_refused():
    approved = copy.deepcopy(EXAMPLE)
    approved["scene"]["status"] = "approved"
    assert "refused" in step.run(approved)


def _row(n: int, kind: str, plan: str) -> dict:
    return logic.revision("s", n, kind, {"plan": {"x": plan}}, [])


def test_undo_and_redo_replay_the_stack():
    rows = [_row(1, "base", "a"), _row(2, "turn", "b"), _row(3, "turn", "c")]
    st = logic.Stack.of(rows)
    assert st.target("undo")["revision"] == 2 and not st.can_redo()
    rows.append(_row(4, "undo", "b"))
    st = logic.Stack.of(rows)
    assert st.target("undo")["revision"] == 1 and st.target("redo")["revision"] == 3
    rows.append(_row(5, "redo", "c"))
    st = logic.Stack.of(rows)
    assert st.done == [1, 2, 3] and not st.can_redo() and st.current({"plan": {"x": "c"}})
    rows.append(_row(6, "turn", "d"))  # a new change after an undo clears what could be redone
    rows.insert(5, _row(5, "undo", "b"))
    assert not logic.Stack.of(rows).can_redo()
    assert logic.prune([_row(i, "turn", "x") for i in range(1, 35)], keep=30) == [1, 2, 3, 4]
