"""`critics_judge`: critics write notes, then CODE picks the plan.

Model critics do not agree with experts, and code can be checked, so a critic never chooses. The shape:

    critics (parallel) → merge their notes → revise the plan once with the notes → judge picks among the candidates

    brief       what the critics read (any data the caller needs)
    candidates  the plans so far; the caller starts it with the first one
    lenses      critic names to ask (the active members of the panel)
    results     one per lens, in order; a critic that failed is None
    notes       merged notes, or [] (no notes, or every critic failed)
    winner      index into `candidates` of the plan the judge picked

The judge is a function of the candidates alone and picks the LOWEST score, the earliest on a tie, so a revision
replaces the first plan only when it is strictly better. A critic that fails is left out; if all fail, the first plan
stands. A revision that raises leaves the first plan standing and keeps the notes (they were still given).
"""
from __future__ import annotations

import logging
import operator
from collections.abc import Callable, Sequence
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.patterns.fan import Worker, wire

_logger = logging.getLogger(__name__)


class JudgeState(TypedDict, total=False):
    brief: Any
    candidates: list[Any]
    lenses: list[str]
    done: Annotated[list[tuple[int, Any]], operator.add]
    results: list[Any]
    notes: list[str]
    error: str
    winner: int


def critics_judge(critic: Worker, merge: Callable[[list[Any]], list[str]],
                  revise: Callable[[dict[str, Any], list[str]], Any] | None,
                  score: Callable[[Any, dict[str, Any]], Sequence[Any]]) -> CompiledStateGraph[Any, Any, Any, Any]:
    """`critic(lens, state)` → its notes or None when it failed; `merge(results)` → the notes to act on (it may raise
    when every critic failed); `revise(state, notes)` → one more candidate; `score(candidate, state)` → a tuple,
    lower wins."""
    g: Any = StateGraph(JudgeState)

    def merged(state: dict[str, Any]) -> dict[str, Any]:
        try:
            return {"notes": merge(list(state.get("results") or []))}
        except Exception:
            _logger.warning("critics failed; the first plan stands", exc_info=True)
            return {"notes": [], "error": "critics failed"}

    def revised(state: dict[str, Any]) -> dict[str, Any]:
        notes = list(state.get("notes") or [])
        if not notes or revise is None:
            return {}
        try:
            return {"candidates": [*state.get("candidates", []), revise(state, notes)]}
        except Exception:
            _logger.warning("the revision failed; the first plan stands", exc_info=True)
            return {"error": "revision failed"}

    def judged(state: dict[str, Any]) -> dict[str, Any]:
        scores = [tuple(score(c, state)) for c in state.get("candidates") or []]
        return {"winner": min(range(len(scores)), key=lambda i: (scores[i], i)) if scores else 0}

    g.add_node("merge", merged)
    g.add_node("revise", revised)
    g.add_node("judge", judged)
    first = wire(g, "critics", critic, items="lenses", done="done", out="results", then="merge")
    g.add_edge(START, first)
    g.add_edge("merge", "revise")
    g.add_edge("revise", "judge")
    g.add_edge("judge", END)
    return g.compile()
