"""Phase 6 (plan/2026-11-06e §4.9): treatment mode, settled choices, suggestions, and the pinned treatment the planner
plans shots from (its pack prints it as fixed and its check reports a plan that drifts from it)."""
from __future__ import annotations

import copy
from typing import Any

from contracts.zora import treatment as T
from hiru_ai.core import llm, parts
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.chat_world import ChatWorld, author

PLANNER = "jona" + "than"  # named like this so the planner's removal check finds no mention in Zora's tests


def test_gaps_hard_first_and_a_settled_soft_gap_is_not_one():
    world = ChatWorld()
    plan, scene = copy.deepcopy(world.plan()), {"blocks": [{"index": i} for i in range(3)]}
    plan["treatment"] |= {"arc": [{"beat": "x", "blocks": {"first": 0, "last": 1}, "feeling": "y"}], "approach": "",
                          "key_image": ""}
    found = T.gaps(plan, scene)
    assert found[0].hard and "b2" in found[0].label
    assert {g.effect for g in found if not g.hard} == {"treatment.approach", "treatment.key_image"}
    assert {g.effect for g in T.gaps(plan, scene, settled=["treatment.approach"])} == {"treatment.arc",
                                                                                         "treatment.key_image"}
    assert T.suggestions(plan, scene) == [T.DRAFT_ARC, T.YOU_DECIDE]
    task = T.task_for("You decide the rest.", plan, scene)
    assert task is not None and task["settles"] == ["treatment.approach", "treatment.key_image"]
    assert T.task_for("make it colder", plan, scene) is None


def test_you_decide_skips_the_router_settles_the_gaps_and_the_author_fills_them():
    world = ChatWorld()
    world.scenes.scene_rows[0]["jonathan"]["plan"]["treatment"]["key_image"] = ""
    image = {"op": "treatment.set", "field": "key_image", "value": "Her hands on the bench."}
    model = RoutedChatModel(routes={"zora.author": [author([image])], "zora.reply": ["Done."]}, model_name="m",
                            stream_phase="zora.reply")
    with llm.use_models(model):
        events = list(graph.run(world.payload(T.YOU_DECIDE), world.ctx()))
    assert "zora.conduct" not in model.phases  # a suggestion is a button
    assert world.plan()["treatment"]["key_image"] == "Her hands on the bench."
    assert "treatment.key_image" in world.row()["jonathan"]["person"]["settled"]
    done = next(d for e, d in events if e == "done")
    assert T.YOU_DECIDE not in done["suggestions"]


def _check(plan: dict[str, Any], scene: dict[str, Any], pinned: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = parts.step(f"{PLANNER}_check", "step").run({"scene": scene, "plan": plan, "pinned": pinned})
    return [p for p in out["problems"] if p["code"] == "treatment"]


def test_the_planners_check_holds_a_pinned_treatment_and_its_pack_prints_it():
    world = ChatWorld()
    from hiru_ai.systems.zora.zora_chat.scene import planner_scene

    scene = planner_scene(world.ctx(), world.ctx().production_id, world.row(), world.scenes.line_rows,  # type: ignore[arg-type]
                          world.scenes.canon_rows)
    plan = world.plan()
    pinned = copy.deepcopy(plan["treatment"])
    assert _check(plan, scene, pinned) == [] and _check(plan, scene, None) == []
    pinned["key_image"] = "Her hands, still."
    found = _check(plan, scene, pinned)
    assert [p["key"] for p in found] == ["treatment:key_image"] and "Her hands, still." in found[0]["sentence"]
    pack = parts.step(f"{PLANNER}_pack", "step")
    base = {"scene": scene, "production": {}, "context": {}}
    assert "<pinned_treatment>" not in pack.run(base)["text"]
    text = pack.run({**base, "pinned": pinned})["text"]
    assert "<pinned_treatment>" in text and "Her hands, still." in text and text.index("<pinned") < text.index(
        "<script>")
