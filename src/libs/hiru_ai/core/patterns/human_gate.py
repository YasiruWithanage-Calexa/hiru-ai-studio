"""`human_gate`: stop for a person, resume with their answer.

With a durable checkpointer the node calls LangGraph's `interrupt()`: the run returns with the questions, and is
resumed hours later (maybe in another instance) with `Command(resume=answers)`. Without one it cannot wait, so it takes
the default answer for each question and says it did (`defaulted`), for a person to review afterwards.

    questions   what to ask (the node is skipped when there are none)
    answers     what is known so far; the gate adds the person's (or the defaults')
    defaulted   the keys that were answered by default
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt


class GateState(TypedDict, total=False):
    questions: list[dict[str, Any]]
    answers: dict[str, Any]
    defaulted: list[str]


def ask_node(*, durable: bool, key: str = "key",
             default: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """The gate as a node for a bigger graph: `state["questions"]` and `state["answers"]` in, answers out."""
    def ask(state: dict[str, Any]) -> dict[str, Any]:
        answers = dict(state.get("answers") or {})
        pending = [q for q in state.get("questions") or [] if q[key] not in answers]
        if not pending:
            return {"answers": answers, "defaulted": []}
        if durable:
            answers.update(interrupt({"questions": pending}) or {})  # the run returns here; resumes with answers
        fallback = default([q for q in pending if q[key] not in answers])
        answers.update(fallback)
        return {"answers": answers, "defaulted": sorted(fallback)}

    return ask


def human_gate(*, durable: bool, key: str = "key",
               default: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The gate on its own: START → ask → END, for a checkpointer and a thread id."""
    g: Any = StateGraph(GateState)
    g.add_node("ask", ask_node(durable=durable, key=key, default=default))
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile()
