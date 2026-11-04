"""`board`: specialists work in parallel → code settles collisions by ownership → advisors review.

The director's board. Each task goes to the specialist it names; specialists never talk to each other and each writes
operations plus a note. `settle` (a step: deterministic code) decides who wins when two crafts wrote the same path.
The review stage runs only when the caller hands it advisors, because it comes AFTER the caller has applied what
landed: the system calls the board once for the specialists and settle, and again with `reviews` for the advisors.

    tasks      [{"craft": "sound", "shots": [2], "instruction": "..."}]   (empty = the specialists stage is skipped)
    outputs    one result per task, in task order
    settled    what `settle(outputs)` returned
    reviews    advisor inputs  →  advice   one result per advisor, in order
"""
from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.patterns.fan import Worker, wire


class BoardState(TypedDict, total=False):
    brief: Any  # what every specialist and advisor may read besides its own item (the shot list, the lead's charter)
    tasks: list[dict[str, Any]]
    outputs: list[Any]
    settled: Any
    reviews: list[Any]
    advice: list[Any]
    done_tasks: Annotated[list[tuple[int, Any]], operator.add]
    done_reviews: Annotated[list[tuple[int, Any]], operator.add]


def board(specialist: Worker, settle: Callable[[list[Any]], Any],
          advisor: Worker | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """`specialist(task, state)` answers one task; `settle(outputs)` settles them; `advisor(item, state)` answers one
    review item. A task whose craft has no member on the board is the caller's to answer (an empty result)."""
    g: Any = StateGraph(BoardState)

    def settled(state: dict[str, Any]) -> dict[str, Any]:
        return {"settled": settle(list(state.get("outputs") or []))}

    g.add_node("settle", settled)
    review = wire(g, "review", advisor or (lambda item, state: None), items="reviews", done="done_reviews",
                  out="advice", then=END)
    first = wire(g, "specialists", specialist, items="tasks", done="done_tasks", out="outputs", then="settle")
    g.add_edge(START, first)
    g.add_edge("settle", review)
    return g.compile()
