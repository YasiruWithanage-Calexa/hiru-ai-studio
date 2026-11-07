"""Phase 4 and 5 (plan/2026-11-06e §3, §4.7): one Zora turn on the product's code, end to end, on in-memory ports with
scripted models (no network). What a turn changes is saved through the planner's write path with every shot keeping
its id, a revision is written for undo, and the reply is written from the ledger."""
from __future__ import annotations

from typing import Any

from contracts.zora.events import ZoraAction
from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.chat_world import ChatWorld, author, conductor

Row = dict[str, Any]


def run(world: ChatWorld, message: str, routes: dict[str, list[Any]], **kw: Any) -> list[tuple[str, Row]]:
    model = RoutedChatModel(routes=routes, model_name="m", stream_phase="zora.reply")
    with llm.use_models(model):
        events = list(graph.run(world.payload(message, **kw), world.ctx()))
    world.model = model  # type: ignore[attr-defined]
    return events


def of(events: list[tuple[str, Row]], name: str) -> list[Row]:
    return [d for e, d in events if e == name]


def test_a_lens_the_person_named_lands_is_saved_with_the_same_shot_ids_and_can_be_undone():
    world = ChatWorld()
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
    events = run(world, "S03 on an 85", {"zora.conduct": [conductor("edit", [lens])],
                                         "zora.reply": ["Done: S03 is on an 85 now."]})
    assert world.plan()["shots"][2]["lens"] == "85mm"
    assert world.shot_ids() == world.original_ids  # frames and prompts stay attached
    assert "S03.lens" in world.row()["jonathan"]["person"]["locked"]  # what the person set is locked
    ops = of(events, "ops")[0]
    assert ops["nothing_changed"] is False and any(c["where"] == "S03" for c in ops["changes"])
    assert [r["kind"] for r in world.revisions.rows] == ["base", "turn"]
    message = of(events, "message")[0]
    assert [b["kind"] for b in message["blocks"]] == ["text", "changes"]
    assert of(events, "done")[0]["revision"] == 2
    assert world.model.phases.count("zora.author") == 0  # an edit the person spelled out needs no author

    back = run(world, "undo that", {})  # in code: no model is asked
    assert world.plan()["shots"][2]["lens"] != "85mm" and world.shot_ids() == world.original_ids
    assert of(back, "done")[0]["lane"] == "undo" and world.model.calls == []
    again = graph.act(ZoraAction(kind="redo", production_id=world.production, scene_id=world.scene_id,
                                 actor_user_id=world.user, can_edit=True), world.ctx())
    assert again.ok and world.plan()["shots"][2]["lens"] == "85mm" and not again.can_redo and again.can_undo


def test_a_craft_task_goes_to_the_one_author_and_its_work_is_kept_to_the_task():
    world = ChatWorld()
    task = {"writes": ["treatment.approach"], "scope": [], "instruction": "make the approach colder"}
    approach = {"op": "treatment.set", "field": "approach", "value": "Cold and observed, from a distance."}
    stray = {"op": "set", "shot": "S01", "field": "size", "value": "ECU"}  # not what the turn asked for
    events = run(world, "make the approach colder", {
        "zora.conduct": [conductor("craft", tasks=[task])],
        "zora.author": [author([approach, stray], notes="Colder.")],
        "zora.reply": ["The approach is colder now."]})
    plan = world.plan()
    assert plan["treatment"]["approach"] == "Cold and observed, from a distance."
    assert plan["shots"][0]["size"] != "ECU"
    ops = of(events, "ops")[0]
    assert any("outside what this turn asked for" in r for r in ops["refused"])
    assert world.model.phases.count("zora.author") == 1


def test_a_task_the_author_did_not_deliver_is_retasked_once_then_reported_never_claimed():
    world = ChatWorld()
    task = {"writes": ["treatment.key_image"], "scope": [], "instruction": "the key image is her hands"}
    events = run(world, "the key image should be her hands, you decide how", {
        "zora.conduct": [conductor("craft", tasks=[task])],
        "zora.author": [author([]), author([])],
        "zora.reply": ["I've changed the key image to her hands."]})
    ops = of(events, "ops")[0]
    assert ops["nothing_changed"] is True and ops["undelivered"]
    assert world.model.phases.count("zora.author") == 2  # one re-task, no more
    text = of(events, "message")[0]["blocks"][0]["text"]
    assert "changed the key image" not in text  # the claim the ledger does not back went
    assert world.revisions.rows == []  # nothing changed, nothing saved


def test_the_conductor_is_asked_again_when_its_lane_would_change_nothing():
    world = ChatWorld()
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
    run(world, "S03 on an 85", {"zora.conduct": [conductor("edit"), conductor("edit", [lens])],
                                "zora.reply": ["Done."]})
    assert world.model.phases.count("zora.conduct") == 2
    assert "YOUR LAST ANSWER COULD NOT BE USED" in world.model.calls[1][1].content
    assert world.plan()["shots"][2]["lens"] == "85mm"


def test_an_op_that_puts_words_in_the_persons_mouth_is_not_applied():
    world = ChatWorld()
    made_up = {"op": "treatment.set", "field": "logline", "value": "A daughter quietly chooses freedom over duty."}
    run(world, "tighten the logline", {"zora.conduct": [conductor("edit", [made_up]), conductor("edit", [made_up])],
                                       "zora.reply": ["Nothing changed."]})
    assert world.plan()["treatment"]["logline"] != made_up["value"]


def test_an_edit_that_would_rewrite_most_of_the_scene_is_offered_as_a_replan_and_nothing_changes():
    world = ChatWorld()
    shots = [{"op": "split", "shot": f"S{n:02d}", "at_block": None} for n in range(1, 4)]
    removes = [{"op": "insert", "after": f"S{n:02d}", "kind": "reaction", "what": "a reaction", "who": ["Anudi"]}
               for n in range(1, 13)]
    before = world.plan()
    events = run(world, "add a reaction after every shot", {
        "zora.conduct": [conductor("edit", removes + shots)], "zora.reply": ["Re-plan it with Jonathan?"]})
    assert of(events, "confirm_reshape") and world.plan() == before and world.revisions.rows == []
    assert of(events, "done")[0]["lane"] == "reshape"


def test_options_are_tried_on_a_copy_and_used_later_with_no_model():
    world = ChatWorld()
    task = {"writes": ["shot.size"], "scope": [1], "instruction": "two ways to open"}
    v = [{"label": "Close first", "ops": [{"op": "set", "shot": "S01", "field": "size", "value": "CU"}]},
         {"label": "Wider", "ops": [{"op": "set", "shot": "S01", "field": "size", "value": "WIDE"}]}]
    before = world.plan()
    events = run(world, "two ways to open", {"zora.conduct": [conductor("options", tasks=[task], variants=2)],
                                             "zora.author": [author(variants=v)], "zora.reply": ["Two openings."]})
    assert world.plan() == before  # nothing is applied until a person uses one
    options = of(events, "proposals")[0]["options"]
    assert [o["label"] for o in options] == ["Close first", "Wider"]
    message = of(events, "message")[0]
    world.director.history.append(message)
    used = graph.act(ZoraAction(kind="use", production_id=world.production, scene_id=world.scene_id,
                                actor_user_id=world.user, can_edit=True, message_id=message["id"], block=2, option=0),
                     world.ctx())
    assert used.ok and world.plan()["shots"][0]["size"] == "CU"
    assert world.director.message(message["id"])["blocks"][2]["chosen"] == 0
    twice = graph.act(ZoraAction(kind="use", production_id=world.production, scene_id=world.scene_id,
                                 actor_user_id=world.user, can_edit=True, message_id=message["id"], block=2, option=1),
                      world.ctx())
    assert not twice.ok


def test_without_a_model_zora_says_so_and_undo_still_answers():
    world = ChatWorld()
    events = list(graph.run(world.payload("make it tenser"), world.ctx()))
    assert "my model is not available" in of(events, "message")[0]["blocks"][0]["text"]
    undo = list(graph.run(world.payload("undo"), world.ctx()))
    assert "nothing to undo" in of(undo, "message")[0]["blocks"][0]["text"]


def test_without_the_revisions_table_an_edit_still_lands_and_undo_says_why_not():
    world = ChatWorld(revisions=False)
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
    events = run(world, "S03 on an 85", {"zora.conduct": [conductor("edit", [lens])], "zora.reply": ["Done."]})
    assert world.plan()["shots"][2]["lens"] == "85mm" and of(events, "done")[0]["revision"] == 0
    undo = list(graph.run(world.payload("undo"), world.ctx()))
    assert "Undo is not available yet" in of(undo, "message")[0]["blocks"][0]["text"]


def test_a_role_that_may_only_comment_changes_nothing():
    world = ChatWorld()
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
    before = world.plan()
    run(world, "S03 on an 85", {"zora.conduct": [conductor("edit", [lens])], "zora.reply": ["I can't."]},
        can_edit=False)
    assert world.plan() == before


def test_a_scene_with_no_planner_plan_is_refused_with_the_way_out():
    world = ChatWorld()
    world.scenes.scene_rows[0]["jonathan"] = {}
    events = list(graph.run(world.payload("hi"), world.ctx()))
    assert of(events, "error") and "Plan this scene with Jonathan first" in of(events, "error")[0]["message"]


def test_a_save_over_a_plan_someone_changed_meanwhile_is_refused():
    world = ChatWorld()
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}

    def conduct(messages: Any) -> Any:  # a re-plan lands while the turn is working
        world.scenes.scene_rows[0] = {**world.scenes.scene_rows[0],
                                      "jonathan": {**world.row()["jonathan"], "plan": {**world.plan(), "x": 1}}}
        import json

        from tests.zora.chat_world import conductor as c
        return json.dumps(c("edit", [lens]))

    events = run(world, "S03 on an 85", {"zora.conduct": [conduct], "zora.reply": ["Done."]})
    assert world.plan()["shots"][2]["lens"] != "85mm"
    assert any("changed this scene's plan while I was working" in r for r in of(events, "ops")[0]["refused"])
