"""`sequential`: A → B → C. Each node reads the state and returns the keys it changes."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

Node = Callable[[dict[str, Any]], dict[str, Any]]


def sequential(state: type, nodes: Sequence[tuple[str, Node]]) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The nodes in order over `state` (a TypedDict). No nodes is a graph that returns its input."""
    g: Any = StateGraph(state)
    previous = START
    for name, node in nodes:
        g.add_node(name, node)
        g.add_edge(previous, name)
        previous = name
    g.add_edge(previous, END)
    return g.compile()
