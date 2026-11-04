"""The pattern library (plan/2026-11-03 Phase 5): each shape alone, with the empty-member and max-round cases."""
from __future__ import annotations

import threading
import time
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from hiru_ai.core.patterns import (
    ask_node,
    board,
    critics_judge,
    fanout,
    generate_critique,
    human_gate,
    mermaid,
    router,
    sequential,
)

# ── fanout ──────────────────────────────────────────────────────────────────────────────────


def test_fanout_returns_results_in_item_order_however_the_branches_finish():
    def work(item: int, state: dict[str, Any]) -> int:
        time.sleep(0.05 * (3 - item))  # the first item finishes last
        return item * 10

    assert fanout(work).invoke({"items": [0, 1, 2]})["outputs"] == [0, 10, 20]


def test_fanout_runs_the_items_side_by_side():
    seen: set[int] = set()
    barrier = threading.Barrier(3, timeout=5)

    def work(item: int, state: dict[str, Any]) -> int:
        seen.add(threading.get_ident())
        barrier.wait()  # only passes when all three are running at once
        return item

    assert fanout(work).invoke({"items": [1, 2, 3]})["outputs"] == [1, 2, 3]
    assert len(seen) == 3


def test_fanout_with_no_items_is_an_empty_result_not_an_error():
    assert fanout(lambda item, state: 1 / 0).invoke({"items": []})["outputs"] == []
    assert fanout(lambda item, state: 1 / 0).invoke({})["outputs"] == []


def test_a_worker_sees_the_brief():
    out = fanout(lambda item, state: f"{item}:{state['brief']}").invoke({"items": ["a"], "brief": "x"})
    assert out["outputs"] == ["a:x"]


# ── sequential ──────────────────────────────────────────────────────────────────────────────


def test_sequential_runs_the_nodes_in_order_and_with_none_returns_the_input():
    from typing import TypedDict

    class S(TypedDict, total=False):
        trail: str

    chain = sequential(S, [("a", lambda s: {"trail": s.get("trail", "") + "a"}),
                           ("b", lambda s: {"trail": s["trail"] + "b"})])
    assert chain.invoke({})["trail"] == "ab"
    assert sequential(S, []).invoke({"trail": "x"})["trail"] == "x"


# ── board ───────────────────────────────────────────────────────────────────────────────────


def _board(advisor: Any = None) -> Any:
    return board(lambda task, state: {"craft": task["craft"], "ops": task.get("ops", [])},
                 lambda outputs: [o["craft"] for o in outputs], advisor)


def test_board_settles_what_the_specialists_returned_in_task_order():
    out = _board().invoke({"tasks": [{"craft": "sound"}, {"craft": "timing"}, {"craft": "sound"}]})
    assert out["settled"] == ["sound", "timing", "sound"]
    assert out.get("advice") == []  # no advisors asked: the review stage is skipped, not failed


def test_board_with_no_tasks_still_settles_the_empty_set():
    assert _board().invoke({"tasks": []})["settled"] == []


def test_board_review_runs_only_the_advisors_it_is_given():
    out = _board(lambda item, state: f"view of {item}").invoke({"tasks": [], "reviews": ["a", "b"]})
    assert out["advice"] == ["view of a", "view of b"]


# ── critics_judge ───────────────────────────────────────────────────────────────────────────


def _judge(*, critics: Any, merge: Any = None, revise: Any = None) -> Any:
    return critics_judge(critics, merge or (lambda results: [n for r in results if r for n in r]), revise,
                         lambda c, state: c["score"])


def test_judge_keeps_the_first_plan_when_nobody_has_a_note():
    graph = _judge(critics=lambda lens, state: [], revise=lambda state, notes: {"score": (0,)})
    out = graph.invoke({"candidates": [{"score": (1,)}], "lenses": ["a", "b"]})
    assert out["notes"] == [] and out["winner"] == 0


def test_judge_takes_the_revision_only_when_strictly_better():
    for revised, expect in (((1,), 0), ((2,), 0), ((0,), 1)):  # a tie keeps the first plan
        graph = _judge(critics=lambda lens, state: ["fix"], revise=lambda state, notes, r=revised: {"score": r})
        assert graph.invoke({"candidates": [{"score": (1,)}], "lenses": ["a"]})["winner"] == expect


def test_judge_is_code_not_the_critics():
    """Even when every critic loves the revision, a worse score loses."""
    graph = _judge(critics=lambda lens, state: ["the second is better"], revise=lambda s, n: {"score": (9,)})
    assert graph.invoke({"candidates": [{"score": (1,)}], "lenses": ["a", "b", "c"]})["winner"] == 0


def test_judge_leaves_out_a_failed_critic_and_survives_all_failing():
    def critic(lens: str, state: dict[str, Any]) -> list[str] | None:
        return ["note"] if lens == "a" else None

    def merge(results: list[Any]) -> list[str]:
        if all(r is None for r in results):
            raise RuntimeError("every reviewer failed")
        return [n for r in results if r for n in r]

    graph = _judge(critics=critic, merge=merge, revise=lambda s, n: {"score": (0,)})
    assert graph.invoke({"candidates": [{"score": (1,)}], "lenses": ["a", "b"]})["winner"] == 1
    out = graph.invoke({"candidates": [{"score": (1,)}], "lenses": ["b", "c"]})
    assert out["notes"] == [] and out["winner"] == 0 and out["error"] == "critics failed"


def test_judge_with_no_critics_keeps_the_first_plan():
    out = _judge(critics=lambda lens, state: ["x"]).invoke({"candidates": [{"score": (3,)}], "lenses": []})
    assert out["winner"] == 0 and out["notes"] == []


def test_a_failing_revision_keeps_the_first_plan_and_the_notes():
    def revise(state: dict[str, Any], notes: list[str]) -> Any:
        raise RuntimeError("planner down")

    out = _judge(critics=lambda lens, state: ["fix S02"], revise=revise).invoke(
        {"candidates": [{"score": (1,)}], "lenses": ["a"]})
    assert out["winner"] == 0 and out["notes"] == ["fix S02"]


# ── generate_critique ───────────────────────────────────────────────────────────────────────


def test_generate_critique_stops_when_the_critic_has_no_notes():
    writes: list[Any] = []
    graph = generate_critique(lambda s, notes: writes.append(notes) or "draft", lambda s, d: [], lambda s, d, r: r)
    out = graph.invoke({"brief": 1})
    assert writes == [None] and out["draft"] == "draft" and out["rounds"] == 0


def test_generate_critique_is_bounded_by_max_rounds_whatever_the_critic_says():
    for rounds in (1, 2, 3):
        drafts = iter(["d0", "d1", "d2", "d3", "d4"])
        graph = generate_critique(lambda s, notes, it=drafts: next(it), lambda s, d: ["always something"],
                                  lambda s, d, r: r, max_rounds=rounds)
        out = graph.invoke({"brief": 1})
        assert out["rounds"] == rounds and out["draft"] == f"d{rounds}"
    zero = generate_critique(lambda s, notes: "d0", lambda s, d: ["x"], lambda s, d, r: r, max_rounds=0)
    assert zero.invoke({"brief": 1})["rounds"] == 0


def test_the_last_revision_is_not_reviewed_again():
    critic_calls: list[Any] = []
    graph = generate_critique(lambda s, notes: "d", lambda s, d: critic_calls.append(d) or ["note"],
                              lambda s, d, r: r, max_rounds=1)
    graph.invoke({"brief": 1})
    assert len(critic_calls) == 1  # one review, one revision, no second review: the model is asked once


def test_generate_critique_accept_decides_whether_a_revision_replaces_the_draft():
    graph = generate_critique(lambda s, notes: "first" if notes is None else "revised", lambda s, d: ["note"],
                              lambda s, d, r: d)  # never accept
    assert graph.invoke({"brief": 1})["draft"] == "first"


def test_generate_critique_hands_the_notes_to_the_writer():
    seen: list[Any] = []
    graph = generate_critique(lambda s, notes: seen.append(notes) or "d", lambda s, d: ["S01 is wide"],
                              lambda s, d, r: r)
    graph.invoke({"brief": 1})
    assert seen == [None, ["S01 is wide"]]


# ── router ──────────────────────────────────────────────────────────────────────────────────


def test_router_sends_the_request_to_the_route_that_handles_it():
    graph = router(lambda s: s["request"], {"edit": lambda s: {"result": "edited"}, "chat": lambda s: {"result": "hi"}})
    assert graph.invoke({"request": "edit"})["result"] == "edited"
    assert graph.invoke({"request": "chat"})["route"] == "chat"


def test_router_unknown_route_goes_to_the_fallback_or_ends():
    routes = {"chat": lambda s: {"result": "hi"}}
    assert router(lambda s: "nope", routes, fallback="chat").invoke({})["result"] == "hi"
    assert "result" not in router(lambda s: "nope", routes).invoke({})


# ── human_gate ──────────────────────────────────────────────────────────────────────────────

Q = [{"key": "a", "title": "A?"}, {"key": "b", "title": "B?"}]


def _defaults(questions: list[dict[str, Any]]) -> dict[str, Any]:
    return {q["key"]: {"value": "default"} for q in questions}


def test_a_gate_without_a_checkpointer_answers_by_default_and_says_so():
    out = human_gate(durable=False, default=_defaults).invoke({"questions": Q, "answers": {"a": {"value": "known"}}})
    assert out["answers"] == {"a": {"value": "known"}, "b": {"value": "default"}} and out["defaulted"] == ["b"]


def test_a_gate_with_nothing_to_ask_does_not_stop():
    out = human_gate(durable=True, default=_defaults).invoke({"questions": Q, "answers": {"a": 1, "b": 2}},
                                                              {"configurable": {"thread_id": "t"}})
    assert out["answers"] == {"a": 1, "b": 2} and "__interrupt__" not in out


def test_a_durable_gate_stops_and_resumes_with_the_persons_answers():
    graph = human_gate(durable=True, default=_defaults)
    from langgraph.graph import StateGraph  # a gate is a node: compile it into a graph that has a checkpointer

    from hiru_ai.core.patterns.human_gate import GateState

    g: Any = StateGraph(GateState)
    g.add_node("ask", ask_node(durable=True, default=_defaults))  # type: ignore[call-overload]
    g.set_entry_point("ask")
    g.set_finish_point("ask")
    app = g.compile(checkpointer=InMemorySaver())
    config: Any = {"configurable": {"thread_id": "job-1"}}
    stopped = app.invoke({"questions": Q}, config)
    assert [q["key"] for q in stopped["__interrupt__"][0].value["questions"]] == ["a", "b"]
    done = app.invoke(Command(resume={"a": {"value": "yes"}}), config)  # b is left: it is defaulted
    assert done["answers"] == {"a": {"value": "yes"}, "b": {"value": "default"}} and done["defaulted"] == ["b"]
    assert graph is not None


# ── drawing ─────────────────────────────────────────────────────────────────────────────────


def test_a_pattern_draws_itself():
    text = mermaid(_board())
    assert text.startswith("---") or text.startswith("graph")
    assert "specialists" in text and "settle" in text and "review" in text
