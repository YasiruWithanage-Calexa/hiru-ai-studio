"""The dependency graph, the re-cut guard and the board (plan/2026-11-06e §4.3, §4.6 step 1, Phase 2): a task comes
only from a change code can prove; an edit that would rewrite most of the scene is offered instead; the one author is
kept to its brief, with refusals the person recognises."""
from __future__ import annotations

from contracts.zora.tasks import Task, merge_tasks
from hiru_ai.steps.zora.zora_board import step as board_step
from hiru_ai.steps.zora.zora_board.logic import settle
from hiru_ai.steps.zora.zora_deps import step as deps_step
from hiru_ai.steps.zora.zora_deps.logic import plan_tasks, recut_guard
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from tests.zora.world import doc


def stale_after(ops: list[dict], name: str = "father_refuses", by: str = "conductor"):
    k = ZoraKernel(doc(name))
    r = k.apply(ops, by=by)
    assert not r.rejected, r.rejected
    return k, plan_tasks(k, r.changes)


def test_a_new_approach_tasks_the_author_on_every_shot_to_change_only_what_contradicts_it():
    _, st = stale_after([{"op": "treatment.set", "field": "approach", "value": "cold, long lenses"}])
    (task,) = st.tasks
    assert task.scope == () and set(task.writes) == {"shot.lens", "shot.angle", "shot.ir.cinematography"}
    assert "change only" in task.instruction.lower() and not st.rewritten


def test_a_sequences_colour_tasks_only_its_own_shots_lighting():
    k, st = stale_after([{"op": "colour.set", "sequence": "B", "field": "grade", "value": "steel blue"}])
    (task,) = st.tasks
    assert task.writes == ("shot.ir.lighting",)
    assert sorted(k.number_of(h) or 0 for h in task.scope) == list(range(7, 12))


def test_an_insert_and_a_split_task_the_new_shots_picture_and_count_as_rewritten():
    k, st = stale_after([{"op": "insert", "after": 5, "kind": "reaction", "what": "he takes it in", "who": ["Kasun"]}])
    (task,) = st.tasks
    assert [k.number_of(h) for h in task.scope] == [6] and "shot.why" in task.writes and "shot.lens" in task.may
    assert len(st.rewritten) == 1 and st.stale == set(task.scope)


def test_a_retime_needs_no_author_and_the_last_shot_touches_the_end_state():
    _, st = stale_after([{"op": "retime", "shot": 15, "take_s": 8}])
    assert st.tasks == [] and st.end_touched


def test_tasks_with_one_scope_are_merged_and_the_whole_scene_stays_whole():
    a = Task(("shot.lens",), (), instruction="colder")
    b = Task(("shot.angle",), (), instruction="lower")
    c = Task(("shot.why",), ("h3",))
    merged = merge_tasks([a, b, c])
    assert len(merged) == 2 and merged[0].writes == ("shot.lens", "shot.angle") and merged[0].scope == ()


def test_the_recut_guard_offers_an_edit_that_would_rewrite_most_of_the_scene_and_leaves_small_ones():
    ops = [{"op": "insert", "after": n, "kind": "reaction", "what": "x", "who": ["Kasun"]} for n in range(1, 10)]
    _, st = stale_after(ops)
    assert recut_guard("edit", "", 15, st) == "it would rewrite 9 of the scene's 15 shots."
    assert recut_guard("shape", "", 15, st) == "" and recut_guard("edit", "edit", 15, st) == ""
    _, small = stale_after(ops[:2])
    assert recut_guard("edit", "", 15, small) == ""


def test_the_deps_step_speaks_in_shot_numbers_after_the_ops():
    d = doc("small")
    out = deps_step.run({"doc": d.model_dump(), "ops": [{"op": "insert", "after": 2, "kind": "reaction",
                                                         "what": "he hears it", "who": ["Dasun"]}]})
    assert out["tasks"][0]["scope"] == [3] and out["stale"] == [3] and out["offer"] == ""


# ── the board ─────────────────────────────────────────────────────────────────────────────────────


def test_the_board_keeps_the_author_to_its_tasks_its_scope_and_the_persons_locks():
    d = doc("small", locked=["S03.lens"])
    out = board_step.run({"doc": d.model_dump(), "tasks": [{"writes": ["shot.lens"], "scope": [2, 3]}], "ops": [
        {"op": "set", "shot": 2, "field": "lens", "value": "85mm"},
        {"op": "set", "shot": 3, "field": "lens", "value": "135mm"},
        {"op": "set", "shot": 1, "field": "lens", "value": "35mm"},
        {"op": "set", "shot": 2, "field": "size", "value": "CU"},
        {"op": "set", "shot": 2, "field": "lines", "value": "x"}]})
    assert out["kept"] == [{"op": "set", "shot": 2, "field": "lens", "value": "85mm"}]
    assert out["refused"] == [
        "the director's lens change on S03 was refused: you set S03's lens yourself",
        "the director's lens change on S01 was refused: it was outside what this turn asked for",
        "the director's size change on S02 was refused: it was outside what this turn asked for",
        "the director's lines change on S02 was refused: the script's lines are never written by the team"]


def test_a_resend_of_the_value_already_there_is_dropped_as_noise_not_reported_as_work():
    d = doc("small")
    out = settle([{"op": "set", "shot": 2, "field": "size", "value": "MCU"},
                  {"shot": 2, "field": "lens", "value": "50mm: plain and near"}],
                 [Task(("shot.size",), ())], d.plan, handles=["h1", "h2", "h3"], locked=[])
    assert out.kept == [] and out.refused == [] and out.noops == 2


def test_a_whole_scene_task_allows_any_shot_and_an_insert_needs_a_task_that_writes_the_shot_list():
    d = doc("small")
    ops = [{"op": "set", "shot": 1, "field": "angle", "value": "low"},
           {"op": "insert", "after": 1, "kind": "reaction", "what": "x", "who": ["Dasun"]}]
    out = settle(ops, [Task(("shot.angle",), ())], d.plan, handles=["h1", "h2", "h3"], locked=[])
    assert [o["op"] for o in out.kept] == ["set"] and len(out.refused) == 1
    out = settle(ops, [Task(("shot.angle", "shot.order"), ())], d.plan, handles=["h1", "h2", "h3"], locked=[])
    assert len(out.kept) == 2
