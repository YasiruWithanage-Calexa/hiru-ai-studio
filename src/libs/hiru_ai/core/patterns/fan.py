"""The fan-out every parallel pattern is built from: one `Send` per item, results gathered in item order.

LangGraph runs the sends of one step side by side. Each result is tagged with its item's position, so the output list
always follows the input list however the branches finish (a board's notes are read in the order its members are
listed). An empty list of items is a normal case: the graph goes straight to the gather node and the output is [].
"""
from __future__ import annotations

import operator
from collections.abc import Callable
from operator import itemgetter
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

Worker = Callable[[Any, dict[str, Any]], Any]  # (item, whole state) -> result


class Branch(TypedDict):
    i: int
    item: Any
    state: dict[str, Any]


class FanState(TypedDict, total=False):
    items: list[Any]
    brief: Any  # what every worker may read besides its own item
    done: Annotated[list[tuple[int, Any]], operator.add]
    outputs: list[Any]


def wire(g: Any, name: str, work: Worker, *, items: str, done: str, out: str, then: str) -> str:
    """Add `name` (entry), `name.work` and `name.gather` to `g`; the gather node continues to `then`.

    `items`, `done` and `out` are state keys: the list to fan over, the reducer channel that collects `(i, result)`
    pairs, and the ordered result list. Returns the entry node's name.
    """
    entry, member, gather = name, f"{name}.work", f"{name}.gather"

    def start(state: dict[str, Any]) -> dict[str, Any]:
        return {}

    def route(state: dict[str, Any]) -> list[Send] | str:
        wanted = list(state.get(items) or [])
        if not wanted:
            return gather
        return [Send(member, Branch(i=i, item=item, state=dict(state))) for i, item in enumerate(wanted)]

    def run(branch: Branch) -> dict[str, Any]:
        return {done: [(branch["i"], work(branch["item"], branch["state"]))]}

    def collect(state: dict[str, Any]) -> dict[str, Any]:
        return {out: [result for _, result in sorted(state.get(done) or [], key=itemgetter(0))]}

    g.add_node(entry, start)
    g.add_node(member, run)
    g.add_node(gather, collect)
    g.add_conditional_edges(entry, route, [member, gather])
    g.add_edge(member, gather)
    g.add_edge(gather, then)
    return entry


def fanout(work: Worker, *, name: str = "member") -> CompiledStateGraph[Any, Any, Any, Any]:
    """Run `work(item, state)` for every item in `state["items"]` at once → `state["outputs"]`, in item order."""
    g: Any = StateGraph(FanState)
    first = wire(g, name, work, items="items", done="done", out="outputs", then=END)
    g.add_edge(START, first)
    return g.compile()
