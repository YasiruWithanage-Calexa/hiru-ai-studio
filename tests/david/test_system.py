"""Phase 3 (plan/2026-11-05e §10): the david_shot_planner system, end to end on localhost with fakes.

The model is scripted with the hand-written phone-call plan (`tests/david/gold.py`) and with patches, so the wiring is
shown: what is handed on, mended, repaired, refused, reported and written, and which tier each call used. It does not
show
that a model can write such an answer: that is what the spike and the blind comparison measure.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from contracts.david.stored import StoredPlan
from contracts.david.wire import DavidWire
from hiru_ai.core import llm
from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.david.david_shot_planner import graph
from hiru_ai.systems.david.david_shot_planner import scene as planner
from tests.david import gold
from tests.david.world import World

MARKS = {"david_author": "planner of Shot Planner David", "david_repair": "repairer of Shot Planner David"}
EMPTY_PATCH: dict[str, Any] = {"replaces": [], "staging": [], "end_state": []}


def route(messages: list[Any]) -> str:
    system = str(messages[0].content)
    return next(k for k, mark in MARKS.items() if mark in system)


def per_tier(model: RoutedChatModel) -> Any:
    """One model instance per tier that shares the routes and the record of calls: `model.models` lists the tiers."""
    return lambda tier: model.model_copy(update={"model_name": tier.name})


def run(world: World, routes: dict[str, list[Any]], **state: Any) -> tuple[dict[str, Any], RoutedChatModel]:
    model = RoutedChatModel(routes=routes, choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        return graph.run(world.payload(**state), world.ctx()), model


def plan_dump(plan: DavidWire | None = None) -> dict[str, Any]:
    return (plan or gold.phone_call()).model_dump(mode="json")


def routes_for(author: Any = None, *repairs: Any) -> dict[str, list[Any]]:
    return {"david_author": [author if author is not None else plan_dump()], "david_repair": list(repairs)}


def without_line(n: int, line: str) -> dict[str, Any]:
    """The phone call with `line` taken out of shot `n` (the author forgot it)."""
    plan = plan_dump()
    plan["shots"][n - 1]["lines"] = [x for x in plan["shots"][n - 1]["lines"] if x != line]
    return plan


def fix_line(n: int, line: str) -> dict[str, Any]:
    """The repairer's patch that puts the line back in shot `n`."""
    shot = plan_dump()["shots"][n - 1]
    return {"replaces": [{"replace_from": n, "replace_to": n, "shots": [{**shot, "n": 1}], "added": []}],
            "staging": [], "end_state": []}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "BACKOFF_S", 0.0)


# ── one scene ────────────────────────────────────────────────────────────────────────────────────


def test_a_scene_that_passes_its_checks_makes_one_model_call_and_is_written_as_ten_shots():
    world = World()
    out, model = run(world, routes_for())
    assert out == {"scenes": 1, "skipped": 0, "shots": 10, "failed": 0} and world.jobs.status == "done"
    assert [route(c) for c in model.calls] == ["david_author"] and model.models == ["author"]
    shots = world.shots()
    assert [s["number"] for s in shots] == list(range(1, 11)) and all(s["planner"] == "david" for s in shots)
    stored = world.stored()
    assert stored.plan == gold.phone_call() and stored.problems == [] and stored.report["calls"] == {
        "author": 1, "repair": 0}
    assert stored.input_hash and stored.end_state == gold.phone_call().end_state
    assert world.row()["status"] == "split" and world.row()["fit_report"]["planner"] == "david"
    assert world.row()["coverage"]["by"] == "david" and world.row()["fit_report"]["total_s"] == 44


def test_every_line_is_bound_to_a_shot_and_keeps_its_own_words():
    world = World()
    run(world, routes_for())
    bound = {ln["id"]: ln for ln in world.scenes.line_rows}
    assert all(bound[i]["shot_id"] for i in world.line_ids[world.scene_id].values())
    assert [bound[i]["text"] for i in world.line_ids[world.scene_id].values()] == [
        b["text"] for b in gold.raw()["blocks"] if b.get("line_id")]
    father = bound[world.short_ids()["L4"]]
    shot = next(s for s in world.shots() if s["id"] == father["shot_id"])
    assert shot["number"] == 5 and shot["sound_mode"] == "voiceover"  # the father's line plays over Anudi's face


def test_the_call_gets_the_context_pack_and_no_other_agent_is_asked():
    world = World()
    _, model = run(world, routes_for())
    user = str(model.calls[0][1].content)
    assert "<production>" in user and "<scene>" in user and "<script>" in user and "<last_shot>" not in user
    assert "(from the canon)" in user and "line [L4]" in user and "shortest take" in user


def test_a_crowded_shot_is_mended_with_no_model_call():
    plan = plan_dump()
    plan["shots"][4]["take_s"] = 4  # the father's 7-word line needs a 6 s take
    world = World()
    _, model = run(world, routes_for(plan))
    stored = world.stored()
    assert [route(c) for c in model.calls] == ["david_author"]
    assert stored.plan.shots[4].take_s == 6 and any("6 s take" in m for m in stored.mended)
    assert stored.report["calls"]["repair"] == 0


def test_a_missing_line_is_repaired_once_by_the_same_strong_model_and_the_patch_is_applied():
    world = World()
    _, model = run(world, routes_for(without_line(2, "L1"), fix_line(2, "L1")))
    assert [route(c) for c in model.calls] == ["david_author", "david_repair"]
    assert model.models == ["author", "repair"]  # one strong model, two efforts
    stored = world.stored()
    assert stored.plan.shots[1].lines == ["L1"] and stored.problems == []
    assert stored.report["calls"] == {"author": 1, "repair": 1} and stored.repairs[0]["accepted"]
    sent = str(model.calls[1][1].content)
    assert "<problems>" in sent and "Line L1 (Dasun" in sent and "<shots>" in sent


def test_two_failed_repairs_are_reported_and_the_scene_is_still_written():
    world = World()
    # the patch that "fixes" the line by dropping another one creates a new failure: refused twice, then reported
    bad = fix_line(2, "L1")
    bad["replaces"][0]["shots"][0]["lines"] = ["L1", "L4"]  # L4 is already spoken in shot 5
    out, model = run(world, routes_for(without_line(2, "L1"), bad, bad))
    assert out["scenes"] == 1 and out["failed"] == 0 and world.jobs.status == "done"
    stored = world.stored()
    assert [route(c) for c in model.calls] == ["david_author", "david_repair", "david_repair"]
    assert [r["accepted"] for r in stored.repairs] == [False, False]
    assert any("Line L1" in p.sentence for p in stored.problems)  # what is left is on the plan, for a person
    assert "tried" not in str(model.calls[1][1].content) and "<tried>" in str(model.calls[2][1].content)


def test_an_empty_repair_ends_the_loop_with_the_problem_reported():
    world = World()
    _, model = run(world, routes_for(without_line(2, "L1"), EMPTY_PATCH, EMPTY_PATCH))
    assert [route(c) for c in model.calls] == ["david_author", "david_repair"]
    assert any(p.fix == "repair" for p in world.stored().problems) and world.jobs.status == "done"


def test_an_addition_that_invents_a_person_is_dropped_by_code_and_never_sent_back():
    plan = plan_dump()
    plan["added"][0]["who"] = ["Waiter"]
    world = World()
    _, model = run(world, routes_for(plan))
    stored = world.stored()
    assert [route(c) for c in model.calls] == ["david_author"] and len(stored.plan.shots) == 9
    assert any(p.fix == "drop" and "Waiter" in p.sentence for p in stored.problems)


def test_a_take_that_cannot_be_made_is_asked_once_more_and_a_second_failure_names_the_classic_planner():
    world = World()
    routes = routes_for()
    routes["david_author"] = [RuntimeError("down"), plan_dump()]
    _, model = run(world, routes)
    assert world.jobs.status == "done" and [route(c) for c in model.calls].count("david_author") == 2
    assert any("asking once more" in line for line in world.stored().report["log"])
    down = World()
    out, _ = run(down, {"david_author": [RuntimeError("down"), RuntimeError("down")], "david_repair": []})
    assert down.jobs.status == "failed" and "classic planner" in down.jobs.fields["error"]
    assert down.row()["david"] == {} and not down.shots() and "scenes" in out


def test_with_no_model_the_job_fails_clearly_and_names_the_classic_planner():
    world = World()
    with llm.use_models(None):
        out = graph.run(world.payload(), world.ctx())
    assert world.jobs.status == "failed" and "classic planner" in world.jobs.fields["error"]
    assert "failed" in out and world.row()["david"] == {} and not world.shots()


def test_an_approved_scene_is_never_touched():
    world = World(status="approved")
    out, model = run(world, {})
    assert out["scenes"] == 0 and out["skipped"] == 1 and not model.calls and not world.shots()


def test_planning_the_scene_again_replaces_its_shots_and_keeps_what_the_scene_had_before_for_comparing():
    classic = [{"id": f"s{n}", "scene_id": "", "number": n, "title": f"classic {n}", "framing": "MS", "duration_s": 6,
                "sound_mode": "dialogue", "camera_link": "cut", "block_start": 0, "block_end": 2, "words": 5,
                "planner": "classic"} for n in (1, 2, 3)]
    world = World(shots=classic)
    for s in world.scenes.shot_rows:
        s["scene_id"] = world.scene_id
    run(world, routes_for())
    first = world.stored()
    assert first.previous["planner"] == "classic" and len(first.previous["shots"]) == 3
    run(world, routes_for(), replan=True)
    assert len(world.shots()) == 10 and world.stored().previous == first.previous


# ── reuse ────────────────────────────────────────────────────────────────────────────────────────


def test_a_scene_whose_input_is_unchanged_keeps_its_plan_with_no_call_unless_a_replan_is_asked():
    world = World()
    run(world, routes_for())
    out, model = run(world, {})
    assert out["scenes"] == 0 and out["skipped"] == 1 and not model.calls
    out, model = run(world, routes_for(), replan=True)
    assert out["scenes"] == 1 and len(model.calls) == 1


def test_a_changed_script_plans_again():
    world = World()
    run(world, routes_for())
    world.row()["script"][0]["text"] = "A bench by the lake, early morning. ANUDI laughs; her phone is face-down."
    out, model = run(world, routes_for())
    assert out["scenes"] == 1 and len(model.calls) == 1


# ── edits ────────────────────────────────────────────────────────────────────────────────────────


def test_removing_an_addition_needs_no_model_and_the_same_addition_never_comes_back():
    world = World()
    run(world, routes_for())
    out, model = run(world, {}, edit={"remove_added": 1})
    assert out["scenes"] == 1 and not model.calls and world.jobs.status == "done"
    stored = world.stored()
    assert len(stored.plan.shots) == 9 and stored.plan.added == [] and len(stored.removed) == 1
    assert [r.kind for r in stored.removed] == ["reaction"]
    # a replan whose author writes it again: code drops it before anyone sees it
    _, model = run(world, routes_for(), replan=True)
    assert len(world.stored().plan.shots) == 9 and [route(c) for c in model.calls] == ["david_author"]
    assert "reaction" in str(model.calls[0][1].content) and "took out" in str(model.calls[0][1].content)


def test_an_addition_that_is_part_of_a_shot_of_the_script_cannot_be_removed_alone():
    world = World()
    plan = plan_dump()
    plan["added"] = [{"shot": 3, "kind": "insert_detail", "what": "the phone", "who": [], "object": "phone"}]
    plan["shots"] = plan["shots"][:9]
    run(world, routes_for(plan))
    out, _ = run(world, {}, edit={"remove_added": 1})
    assert world.jobs.status == "failed" and "note" in world.jobs.fields["error"] and out["failed"] == 1


def test_a_note_makes_one_repair_with_the_persons_note_as_the_problem():
    world = World()
    run(world, routes_for())
    patch = fix_line(1, "")  # any valid patch: shot 1 as it is
    patch["replaces"][0]["shots"][0] = {**plan_dump()["shots"][0], "n": 1, "why": "Establish the bench, closer."}
    out, model = run(world, {"david_repair": [patch]}, edit={"note": "Start closer on Anudi."})
    assert out["scenes"] == 1 and [route(c) for c in model.calls] == ["david_repair"]
    assert "Start closer on Anudi." in str(model.calls[0][1].content) and "<note>" in str(model.calls[0][1].content)
    assert world.stored().plan.shots[0].why == "Establish the bench, closer."


# ── the pool and the budget ──────────────────────────────────────────────────────────────────────


def three_scenes(**kw: Any) -> World:
    world = World(**kw)
    world.add_scene(2)
    world.add_scene(3)
    return world


def test_unlinked_scenes_are_each_planned_and_written():
    world = three_scenes()
    out, model = run(world, {"david_author": [plan_dump() for _ in range(3)], "david_repair": []},
                     scene_ids=[str(r["id"]) for r in world.scene_rows])
    assert out["scenes"] == 3 and len(model.calls) == 3 and all(StoredPlan.load(r["david"]) for r in world.scene_rows)


def test_past_the_time_budget_no_new_scene_starts_and_the_rest_go_to_a_fresh_delivery(monkeypatch: pytest.MonkeyPatch):
    world = three_scenes()
    model = RoutedChatModel(routes={"david_author": [plan_dump() for _ in range(3)], "david_repair": []}, choose=route,
                            model_name="model")
    ids = [str(r["id"]) for r in world.scene_rows]
    monkeypatch.setenv("DAVID_WORKERS", "1")
    get_settings.cache_clear()
    payload = world.payload(scene_ids=ids)
    with llm.use_models(per_tier(model)):
        out = graph.run(payload, world.ctx(), budget_s=-1.0)
    assert out["scenes"] == 1 and out["continued"] == 2 and len(model.calls) == 1
    nxt = world.jobs.advanced[0]
    assert nxt["again"] and len(nxt["state"]["scene_ids"]) == 2 and nxt["state"]["progress"]["scenes"] == 1


# ── the join between scenes ──────────────────────────────────────────────────────────────────────


def chained(**kw: Any) -> World:
    world = World(**kw)
    world.add_scene(2, time_of_day="CONTINUOUS")
    return world


def test_a_scene_that_carries_on_is_given_the_end_state_and_the_last_shot_of_the_one_before_word_for_word():
    world = chained()
    ids = [str(r["id"]) for r in world.scene_rows]
    second = plan_dump()
    out, model = run(world, {"david_author": [plan_dump(), second], "david_repair": [EMPTY_PATCH]}, scene_ids=ids)
    assert out["scenes"] == 2
    first_user, second_user = (str(model.calls[0][1].content), str(model.calls[1][1].content))
    assert "(from the canon)" in first_user and "<last_shot>" not in first_user
    assert "(from the canon)" not in second_user and "continuous" in second_user
    assert "on the path away from the bench" in second_user  # the end state of scene 1
    last_ir = json.dumps(gold.phone_call().shots[-1].ir, ensure_ascii=False, separators=(",", ":"))
    assert last_ir in second_user  # its last shot's IR, word for word (D8)
    assert world.stored(ids[1]).link.kind == "continuous" and world.stored(ids[0]).link.kind == ""


def test_a_scene_that_opens_somewhere_else_than_the_one_before_ended_gets_one_repair_for_the_seam():
    world = chained()
    ids = [str(r["id"]) for r in world.scene_rows]
    routes = {"david_author": [plan_dump(), plan_dump()], "david_repair": [EMPTY_PATCH, EMPTY_PATCH]}
    out, model = run(world, routes, scene_ids=ids)
    stored = world.stored(ids[1])
    assert [route(c) for c in model.calls] == ["david_author", "david_author", "david_repair"]  # at most one
    # it opens at the bench and the scene before ended on the path
    assert any("Anudi" in p.sentence and "path" in p.sentence for p in stored.seams)
    assert out["scenes"] == 2 and world.jobs.status == "done"


def test_a_chain_is_cut_by_the_budget_and_carries_on_in_the_next_delivery_from_the_stored_end_state():
    world = chained()
    ids = [str(r["id"]) for r in world.scene_rows]
    model = RoutedChatModel(routes={"david_author": [plan_dump(), plan_dump()], "david_repair": [EMPTY_PATCH]},
                            choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=ids), world.ctx(), budget_s=-1.0)
        assert out["scenes"] == 1 and out["continued"] == 1
        left = world.jobs.advanced[0]["state"]["scene_ids"]
        assert left == [ids[1]]
        graph.run(world.payload(scene_ids=left), world.ctx(), budget_s=-1.0)  # the fresh delivery: nothing in memory
    second_user = str(model.calls[1][1].content)
    assert "on the path away from the bench" in second_user  # read from scenes.david, not from memory
    assert world.stored(ids[1]).start is not None


def test_in_episode_order_every_scene_follows_the_one_before_and_a_replan_cascades_until_an_end_state_is_unchanged():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    plans = [plan_dump() for _ in range(3)]
    run(world, {"david_author": plans, "david_repair": [EMPTY_PATCH] * 4}, scene_ids=ids, order="episode")
    assert [world.stored(i).link.kind for i in ids] == ["", "carry", "carry"]
    # replan the first scene with a different end state: the scenes after it are replanned in order, once each
    changed = plan_dump()
    changed["end_state"]["time"] = "dusk"
    model = RoutedChatModel(routes={"david_author": [changed, plan_dump(), plan_dump()],
                                    "david_repair": [EMPTY_PATCH] * 4}, choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    # scene 2 was out of date (its start changed) and is planned again; its end state comes out the same, so scene 3 is
    # left alone
    assert [route(c) for c in model.calls].count("david_author") == 2


def test_a_replan_whose_end_state_comes_out_the_same_does_not_touch_the_scenes_after_it():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    run(world, {"david_author": [plan_dump() for _ in range(3)], "david_repair": [EMPTY_PATCH] * 4}, scene_ids=ids,
        order="episode")
    model = RoutedChatModel(routes={"david_author": [plan_dump()], "david_repair": []}, choose=route,
                            model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    assert out["scenes"] == 1 and len(model.calls) == 1  # the same end state: the cascade stops at once


def test_an_approved_scene_in_a_chain_is_not_replanned_and_stops_the_cascade():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    run(world, {"david_author": [plan_dump() for _ in range(3)], "david_repair": [EMPTY_PATCH] * 4}, scene_ids=ids,
        order="episode")
    world.scene_rows[1]["status"] = "approved"
    changed = plan_dump()
    changed["end_state"]["time"] = "dusk"
    model = RoutedChatModel(routes={"david_author": [changed], "david_repair": []}, choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    assert out["scenes"] == 1 and len(model.calls) == 1
    assert world.stored(ids[1]).input_hash and world.row(ids[1])["status"] == "approved"
