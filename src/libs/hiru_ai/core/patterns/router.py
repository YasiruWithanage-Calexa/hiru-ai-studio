"""`router`: classify, then `Command(goto=…)` to the route that handles it.

The classifier is a function (a rule, or a model's answer already validated); an unknown route goes to `fallback` when
the router has one, else the graph ends. Routes are nodes: each reads the state and returns the keys it changes.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

Node = Callable[[dict[str, Any]], dict[str, Any]]


class RouterState(TypedDict, total=False):
    request: Any
    route: str
    result: Any


def router(classify: Callable[[dict[str, Any]], str], routes: Mapping[str, Node],
           *, fallback: str | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    g: Any = StateGraph(RouterState)
    names = list(routes)

    def decide(state: dict[str, Any]) -> Command[Any]:
        route = classify(state)
        target = route if route in routes else fallback
        return Command(update={"route": route}, goto=target if target in routes else END)

    g.add_node("classify", decide, destinations=(*names, END))
    for name in names:
        g.add_node(name, routes[name])
        g.add_edge(name, END)
    g.add_edge(START, "classify")
    return g.compile()
