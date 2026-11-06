"""Phase 3 (plan/2026-11-06b §4.3, §7): the jonathan_shot_planner system, end to end on localhost with fakes.

The model is scripted with the hand-written phone-call plan (`tests/jonathan/gold.py`) and variations of it, so the
wiring is shown: what is handed on, mended, revised, kept or not kept, reported and written, and which tier each call
used. The stabiliser is the cinematic lab's: a draft, code's findings, at most two revise passes from the best plan so
far, the best kept. It does not show that a model can write such an answer: that is what the lab and the gate measure.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from contracts.jonathan.stored import StoredPlan
from contracts.jonathan.wire import JonathanWire
from hiru_ai.core import llm
from hiru_ai.core.settings import get_settings
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.jonathan.jonathan_shot_planner import graph
from hiru_ai.systems.jonathan.jonathan_shot_planner import scene as planner
from tests.jonathan import gold
from tests.jonathan.world import World


def route(messages: list[Any]) -> str:
    """The author and the reviser share one prompt; only the reviser is sent a draft."""
    return "jonathan_revise" if "<draft>" in str(messages[1].content) else "jonathan_author"


def per_tier(model: RoutedChatModel) -> Any:
    """One model instance per tier that shares the routes and the record of calls: `model.models` lists the tiers."""
    return lambda tier: model.model_copy(update={"model_name": tier.name})


def run(world: World, routes: dict[str, list[Any]], **state: Any) -> tuple[dict[str, Any], RoutedChatModel]:
    model = RoutedChatModel(routes=routes, choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        return graph.run(world.payload(**state), world.ctx()), model


def plan_dump(plan: JonathanWire | None = None) -> dict[str, Any]:
    return (plan or gold.phone_call()).model_dump(mode="json")


def routes_for(author: Any = None, *revises: Any) -> dict[str, list[Any]]:
    return {"jonathan_author": [author if author is not None else plan_dump()], "jonathan_revise": list(revises)}


def without_line(n: int, line: str) -> dict[str, Any]:
    """The phone call with `line` taken out of shot `n` (the author forgot it): a hard fault."""
    plan = plan_dump()
    plan["shots"][n - 1]["lines"] = [x for x in plan["shots"][n - 1]["lines"] if x != line]
    return plan


def without_reaction() -> dict[str, Any]:
    """The phone call with no reaction to the goodbye: no fault, one craft gap."""
    return plan_dump(gold.phone_call().without({13}))


def calls(model: RoutedChatModel) -> list[str]:
    return [route(c) for c in model.calls]


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(planner, "BACKOFF_S", 0.0)


# ── one scene ────────────────────────────────────────────────────────────────────────────────────


def test_a_clean_draft_makes_one_model_call_and_is_written_as_fifteen_shots():
    world = World()
    out, model = run(world, routes_for())
    assert out == {"scenes": 1, "skipped": 0, "shots": 15, "failed": 0} and world.jobs.status == "done"
    assert calls(model) == ["jonathan_author"] and model.models == ["jonathan"]
    shots = world.shots()
    assert [s["number"] for s in shots] == list(range(1, 16)) and all(s["planner"] == "jonathan" for s in shots)
    stored = world.stored()
    assert stored.plan == gold.phone_call() and stored.problems == [] and stored.report["calls"] == {
        "author": 1, "revise": 0}
    assert stored.report["score"] == [0, 0] and stored.report["first_score"] == [0, 0] and stored.repairs == []
    assert {m["key"] for m in stored.measures} >= {"opens", "reactions", "motion", "grade"}
    assert stored.input_hash and stored.end_state == gold.phone_call().end_state
    assert world.row()["status"] == "split" and world.row()["fit_report"]["planner"] == "jonathan"
    assert world.row()["fit_report"]["total_s"] == 66 and world.row()["fit_report"]["use_s"] == 46
    coverage = world.row()["coverage"]
    assert coverage["by"] == "jonathan" and coverage["motif"] == gold.phone_call().treatment.key_image


def test_jonathans_own_sizes_reach_the_shots_rows_as_their_nearest_and_the_plan_keeps_them():
    world = World()
    run(world, routes_for())
    framings = [s["framing"] for s in world.shots()]
    assert framings[0] == "WIDE" and framings[10] == "CU"  # EWS and ECU
    assert world.stored().plan.shots[0].size == "EWS" and world.shots()[0]["card"]["use_s"] == 3


def test_every_line_is_bound_to_a_shot_and_keeps_its_own_words():
    world = World()
    run(world, routes_for())
    bound = {ln["id"]: ln for ln in world.scenes.line_rows}
    assert all(bound[i]["shot_id"] for i in world.line_ids[world.scene_id].values())
    assert [bound[i]["text"] for i in world.line_ids[world.scene_id].values()] == [
        b["text"] for b in gold.raw()["blocks"] if b.get("line_id")]
    father = bound[world.short_ids()["L4"]]
    shot = next(s for s in world.shots() if s["id"] == father["shot_id"])
    assert shot["number"] == 7 and shot["sound_mode"] == "voiceover"  # the father's line plays over Anudi's face


def test_the_call_gets_the_labs_context_pack():
    world = World()
    _, model = run(world, routes_for())
    user = str(model.calls[0][1].content)
    assert "<production>" in user and "<scene>" in user and "<script>" in user and "<last_shot>" not in user
    assert "(from the canon)" in user and "line [L4]" in user and "shortest take" in user
    assert "who they are: Anudi in the drama" in user  # the canon card's summary: the essence the team plans from
    assert "The length is the producer's budget (about 90 s)" in user
    assert "Father (on the phone), heard not seen" in user


def test_a_crowded_shot_is_mended_with_no_model_call():
    plan = plan_dump()
    plan["shots"][6]["take_s"] = 4  # the father's line needs a 6 s take
    world = World()
    _, model = run(world, routes_for(plan))
    stored = world.stored()
    assert calls(model) == ["jonathan_author"]
    assert stored.plan.shots[6].take_s == 6 and any("6 s take" in m for m in stored.mended)
    assert stored.report["calls"]["revise"] == 0


def test_a_fault_is_sent_back_with_the_draft_and_a_whole_corrected_plan_is_kept():
    world = World()
    _, model = run(world, routes_for(without_line(2, "L1"), plan_dump()))
    assert calls(model) == ["jonathan_author", "jonathan_revise"]
    assert model.models == ["jonathan", "jonathan"]  # one tier for the author and the reviser
    stored = world.stored()
    assert stored.plan == gold.phone_call() and stored.problems == []
    assert stored.report["calls"] == {"author": 1, "revise": 1} and stored.report["first_score"][0] > 0
    assert stored.repairs[0]["accepted"] and stored.repairs[0]["after"] == [0, 0]
    sent = str(model.calls[1][1].content)
    assert sent.startswith(str(model.calls[0][1].content))  # the author's own message, then its draft
    assert "<draft>" in sent and "Line L1 (Dasun" in sent and "fix every one" in sent
    assert str(model.calls[1][0].content) == str(model.calls[0][0].content)  # the author's own prompt


def test_a_craft_gap_alone_is_sent_back_too_and_the_better_plan_is_kept():
    world = World()
    _, model = run(world, routes_for(without_reaction(), plan_dump()))
    assert calls(model) == ["jonathan_author", "jonathan_revise"]
    sent = str(model.calls[1][1].content)
    assert "Problems code found in the draft (fix every one):\n- none" in sent and "reaction or listener" in sent
    stored = world.stored()
    assert stored.report["first_score"] == [0, 1] and stored.report["score"] == [0, 0] and len(stored.plan.shots) == 15


def test_two_passes_that_are_not_better_are_not_kept_and_what_is_left_is_reported():
    world = World()
    broken = without_line(2, "L1")
    out, model = run(world, routes_for(broken, broken, broken))
    assert out["scenes"] == 1 and out["failed"] == 0 and world.jobs.status == "done"
    stored = world.stored()
    assert calls(model) == ["jonathan_author", "jonathan_revise", "jonathan_revise"]  # never a third
    assert [r["accepted"] for r in stored.repairs] == [False, False]
    assert any("Line L1" in p.sentence for p in stored.problems)  # what is left is on the plan, for a person


def test_a_worse_pass_is_never_built_on_the_next_pass_starts_again_from_the_best():
    world = World()
    worse = without_line(2, "L1")
    worse["shots"][7]["lines"] = []  # and L6 is lost as well
    _, model = run(world, routes_for(without_line(2, "L1"), worse, plan_dump()))
    assert calls(model) == ["jonathan_author", "jonathan_revise", "jonathan_revise"]
    first_draft, second_draft = (str(c[1].content).split("<draft>")[1].split("</draft>")[0] for c in model.calls[1:])
    assert first_draft == second_draft  # the worse plan was never sent back as the draft
    stored = world.stored()
    assert [r["accepted"] for r in stored.repairs] == [False, True] and stored.plan == gold.phone_call()


def test_a_reviser_that_cannot_answer_leaves_the_best_plan_standing():
    world = World()
    _, model = run(world, routes_for(without_reaction(), RuntimeError("down")))
    stored = world.stored()
    assert world.jobs.status == "done" and calls(model) == ["jonathan_author", "jonathan_revise"]
    assert len(stored.plan.shots) == 14 and stored.repairs[0]["result"] == "no answer"


def test_an_addition_that_invents_a_person_is_dropped_by_code_and_never_sent_back():
    plan = plan_dump()
    plan["added"][2]["who"] = ["Waiter"]  # the reaction to the goodbye shows a stranger
    world = World()
    _, model = run(world, routes_for(plan, plan_dump()))
    stored = world.stored()
    assert any(p["fix"] == "drop" and "Waiter" in p["sentence"] for p in stored.report["first_pass"]) or \
        any("Waiter" in d for d in stored.report["checks"]["dropped"]) or "Waiter" not in json.dumps(stored.data())
    assert all("Waiter" not in str(c[1].content).split("<findings>")[-1] for c in model.calls[1:])


def test_a_take_that_cannot_be_made_is_asked_once_more_and_a_second_failure_names_the_classic_planner():
    world = World()
    routes = routes_for()
    routes["jonathan_author"] = [RuntimeError("down"), plan_dump()]
    _, model = run(world, routes)
    assert world.jobs.status == "done" and calls(model).count("jonathan_author") == 2
    assert any("asking once more" in line for line in world.stored().report["log"])
    down = World()
    out, _ = run(down, {"jonathan_author": [RuntimeError("down"), RuntimeError("down")], "jonathan_revise": []})
    assert down.jobs.status == "failed" and "classic planner" in down.jobs.fields["error"]
    assert down.row()["jonathan"] == {} and not down.shots() and "scenes" in out


def test_with_no_model_the_job_fails_clearly_and_names_the_classic_planner():
    world = World()
    with llm.use_models(None):
        out = graph.run(world.payload(), world.ctx())
    assert world.jobs.status == "failed" and "classic planner" in world.jobs.fields["error"]
    assert "failed" in out and world.row()["jonathan"] == {} and not world.shots()


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
    assert len(world.shots()) == 15 and world.stored().previous == first.previous


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
    assert len(stored.plan.shots) == 14 and [a.shot for a in stored.plan.added] == [8, 12]
    assert [r.kind for r in stored.removed] == ["reaction"]
    # a replan whose author writes it again: code drops it before anyone sees it, and a reviser that writes it again
    # is no better, so the plan without it stands
    _, model = run(world, routes_for(plan_dump(), plan_dump(), plan_dump()), replan=True)
    assert len(world.stored().plan.shots) == 14 and calls(model)[0] == "jonathan_author"
    assert "reaction" in str(model.calls[0][1].content) and "took out" in str(model.calls[0][1].content)


def test_an_addition_that_is_part_of_a_shot_of_the_script_cannot_be_removed_alone():
    world = World()
    plan = plan_dump()
    plan["added"] = [{"shot": 4, "kind": "insert_detail", "what": "the phone", "who": [], "object": "phone"},
                     *plan["added"]]
    run(world, routes_for(plan))
    assert [a.shot for a in world.stored().plan.added] == [3, 4, 9, 13]  # in shot order: the insert is number 2
    out, _ = run(world, {}, edit={"remove_added": 2})
    assert world.jobs.status == "failed" and "note" in world.jobs.fields["error"] and out["failed"] == 1


def test_a_note_makes_one_revise_pass_with_the_persons_note():
    world = World()
    run(world, routes_for())
    closer = plan_dump()
    closer["shots"][0]["why"] = "The world, closer: the bench and the two of them."
    out, model = run(world, {"jonathan_revise": [closer]}, edit={"note": "Start closer on Anudi."})
    assert out["scenes"] == 1 and calls(model) == ["jonathan_revise"]
    sent = str(model.calls[0][1].content)
    assert "A person's note on the plan" in sent and "Start closer on Anudi." in sent
    stored = world.stored()
    assert stored.plan.shots[0].why == "The world, closer: the bench and the two of them."
    assert stored.repairs[-1]["kind"] == "note" and stored.repairs[-1]["accepted"]


# ── the pool and the budget ──────────────────────────────────────────────────────────────────────


def three_scenes(**kw: Any) -> World:
    world = World(**kw)
    world.add_scene(2)
    world.add_scene(3)
    return world


def test_unlinked_scenes_are_each_planned_and_written():
    world = three_scenes()
    out, model = run(world, {"jonathan_author": [plan_dump() for _ in range(3)], "jonathan_revise": []},
                     scene_ids=[str(r["id"]) for r in world.scene_rows])
    assert out["scenes"] == 3 and len(model.calls) == 3
    assert all(StoredPlan.load(r["jonathan"]) for r in world.scene_rows)


def test_past_the_time_budget_no_new_scene_starts_and_the_rest_go_to_a_fresh_delivery(monkeypatch: pytest.MonkeyPatch):
    world = three_scenes()
    model = RoutedChatModel(routes={"jonathan_author": [plan_dump() for _ in range(3)], "jonathan_revise": []},
        choose=route,
                            model_name="model")
    ids = [str(r["id"]) for r in world.scene_rows]
    monkeypatch.setenv("JONATHAN_WORKERS", "1")
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
    out, model = run(world, {"jonathan_author": [plan_dump(), second], "jonathan_revise": [plan_dump()]}, scene_ids=ids)
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
    routes = {"jonathan_author": [plan_dump(), plan_dump()], "jonathan_revise": [plan_dump(), plan_dump()]}
    out, model = run(world, routes, scene_ids=ids)
    stored = world.stored(ids[1])
    assert [route(c) for c in model.calls] == ["jonathan_author", "jonathan_author", "jonathan_revise"]  # at most one
    # it opens at the bench and the scene before ended on the path
    assert any("Anudi" in p.sentence and "path" in p.sentence for p in stored.seams)
    assert out["scenes"] == 2 and world.jobs.status == "done"


def test_a_chain_is_cut_by_the_budget_and_carries_on_in_the_next_delivery_from_the_stored_end_state():
    world = chained()
    ids = [str(r["id"]) for r in world.scene_rows]
    model = RoutedChatModel(routes={"jonathan_author": [plan_dump(), plan_dump()], "jonathan_revise": [plan_dump()]},
                            choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=ids), world.ctx(), budget_s=-1.0)
        assert out["scenes"] == 1 and out["continued"] == 1
        left = world.jobs.advanced[0]["state"]["scene_ids"]
        assert left == [ids[1]]
        graph.run(world.payload(scene_ids=left), world.ctx(), budget_s=-1.0)  # the fresh delivery: nothing in memory
    second_user = str(model.calls[1][1].content)
    assert "on the path away from the bench" in second_user  # read from scenes.jonathan, not from memory
    assert world.stored(ids[1]).start is not None


def test_in_episode_order_every_scene_follows_the_one_before_and_a_replan_cascades_until_an_end_state_is_unchanged():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    plans = [plan_dump() for _ in range(3)]
    run(world, {"jonathan_author": plans, "jonathan_revise": [plan_dump() for _ in range(4)]}, scene_ids=ids,
        order="episode")
    assert [world.stored(i).link.kind for i in ids] == ["", "carry", "carry"]
    # replan the first scene with a different end state: the scenes after it are replanned in order, once each
    changed = plan_dump()
    changed["end_state"]["time"] = "dusk"
    model = RoutedChatModel(routes={"jonathan_author": [changed, plan_dump(), plan_dump()],
                                    "jonathan_revise": [plan_dump() for _ in range(4)]},
                            choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    # scene 2 was out of date (its start changed) and is planned again; its end state comes out the same, so scene 3 is
    # left alone
    assert [route(c) for c in model.calls].count("jonathan_author") == 2


def test_a_replan_whose_end_state_comes_out_the_same_does_not_touch_the_scenes_after_it():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    run(world, {"jonathan_author": [plan_dump() for _ in range(3)], "jonathan_revise": [plan_dump() for _ in range(4)]},
        scene_ids=ids,
        order="episode")
    model = RoutedChatModel(routes={"jonathan_author": [plan_dump()], "jonathan_revise": []}, choose=route,
                            model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    assert out["scenes"] == 1 and len(model.calls) == 1  # the same end state: the cascade stops at once


def test_an_approved_scene_in_a_chain_is_not_replanned_and_stops_the_cascade():
    world = three_scenes()
    ids = [str(r["id"]) for r in world.scene_rows]
    run(world, {"jonathan_author": [plan_dump() for _ in range(3)], "jonathan_revise": [plan_dump() for _ in range(4)]},
        scene_ids=ids,
        order="episode")
    world.scene_rows[1]["status"] = "approved"
    changed = plan_dump()
    changed["end_state"]["time"] = "dusk"
    model = RoutedChatModel(routes={"jonathan_author": [changed], "jonathan_revise": []},
        choose=route, model_name="model")
    with llm.use_models(per_tier(model)):
        out = graph.run(world.payload(scene_ids=[ids[0]], order="episode", replan=True), world.ctx())
    assert out["scenes"] == 1 and len(model.calls) == 1
    assert world.stored(ids[1]).input_hash and world.row(ids[1])["status"] == "approved"
