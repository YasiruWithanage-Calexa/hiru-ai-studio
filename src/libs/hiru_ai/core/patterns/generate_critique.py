"""`generate_critique`: a writer and a critic, bounded.

    write → critique → (notes? → write again with the notes → accept?) … up to `max_rounds`

Open-ended "make it better" loops drift away from the script and cost without a ceiling, so the loop has a hard bound
(`max_rounds`, default 1) and a stop rule in code: no notes ends it, and `accept` decides whether a revision replaces
the draft (the shot reviewer keeps a revised shot only when the free checks find no more problems in it).

    draft       the current best (the writer's first answer, then whatever `accept` kept)
    notes       the last round's notes
    rounds      how many revisions were attempted
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class CritiqueState(TypedDict, total=False):
    brief: Any
    draft: Any
    notes: list[str]
    revised: Any
    rounds: int


def generate_critique(write: Callable[[dict[str, Any], list[str] | None], Any],
                      critique: Callable[[dict[str, Any], Any], list[str]],
                      accept: Callable[[dict[str, Any], Any, Any], Any],
                      *, max_rounds: int = 1) -> CompiledStateGraph[Any, Any, Any, Any]:
    """`write(state, notes)` → a draft (notes None = the first); `critique(state, draft)` → notes ([] = content);
    `accept(state, draft, revised)` → the draft to keep."""
    g: Any = StateGraph(CritiqueState)

    def first(state: dict[str, Any]) -> dict[str, Any]:
        return {"draft": write(state, None), "rounds": 0, "notes": []}

    def review(state: dict[str, Any]) -> dict[str, Any]:
        return {"notes": list(critique(state, state["draft"]))}

    def revise(state: dict[str, Any]) -> dict[str, Any]:
        revised = write(state, list(state["notes"]))
        return {"revised": revised, "draft": accept(state, state["draft"], revised),
                "rounds": int(state.get("rounds", 0)) + 1}

    def again(state: dict[str, Any]) -> str:
        return "revise" if state.get("notes") and int(state.get("rounds", 0)) < max_rounds else END

    def next_round(state: dict[str, Any]) -> str:
        """A revision is reviewed again only if another round is allowed: the last one is not."""
        return "critique" if int(state.get("rounds", 0)) < max_rounds else END

    g.add_node("write", first)
    g.add_node("critique", review)
    g.add_node("revise", revise)
    g.add_edge(START, "write")
    g.add_edge("write", "critique")
    g.add_conditional_edges("critique", again, ["revise", END])
    g.add_conditional_edges("revise", next_round, ["critique", END])
    return g.compile()
