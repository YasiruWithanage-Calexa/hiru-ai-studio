"""The pattern library: the common shapes of an AI flow, written and tested once (plan/2026-11-03 §5.5).

A panel configures a pattern with its members instead of re-coding the wiring. A shape that fits none is written as
plain LangGraph in the panel's own `graph.py`: patterns are a convenience, not a cage.

| pattern            | shape                                                   |
|--------------------|---------------------------------------------------------|
| `sequential`       | A → B → C                                               |
| `fanout`           | one `Send` per item, results gathered in item order     |
| `board`            | fanout → settle by ownership (code) → advisors          |
| `critics_judge`    | critics write notes → revise once → code judge picks    |
| `generate_critique`| writer ⇄ critic, bounded, with an accept rule           |
| `router`           | classify → `Command(goto=…)`                            |
| `human_gate`       | `interrupt()` → resume with the person's answer         |
"""
from __future__ import annotations

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from hiru_ai.core.manifest import PATTERNS
from hiru_ai.core.patterns.board import board
from hiru_ai.core.patterns.critics_judge import critics_judge
from hiru_ai.core.patterns.fan import fanout
from hiru_ai.core.patterns.generate_critique import generate_critique
from hiru_ai.core.patterns.human_gate import ask_node, human_gate
from hiru_ai.core.patterns.router import router
from hiru_ai.core.patterns.sequential import sequential


def mermaid(graph: CompiledStateGraph[Any, Any, Any, Any]) -> str:
    """The graph's wiring as Mermaid text (snapshot-tested: a wiring change shows up in review)."""
    return str(graph.get_graph().draw_mermaid()).strip() + "\n"


__all__ = ["PATTERNS", "ask_node", "board", "critics_judge", "fanout", "generate_critique", "human_gate", "mermaid",
           "router", "sequential"]
