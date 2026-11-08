"""sable_chat: one synchronous, STREAMED Sable turn over the whole production (plan/2026-11-08 §4.1, Phase 5).

Not a job, like Zora and the classic director chat: the API checks who is asking, stores their message and proxies this
function's event stream back to the browser (`contracts.sable.events`). The graph is the turn's shape:

    read → loop → guard → save

    run(req, ctx, stop)   the events of one turn, in order; `stop` set = the person pressed Stop (the turn still saves)
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.sable.events import SableTurnPayload
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.sable.sable_chat.state import State
from hiru_ai.systems.sable.sable_chat.turn import Turn

Event = tuple[str, dict[str, Any]]


def build(req: SableTurnPayload, ctx: RunContext,
          stop: threading.Event | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    writer: dict[str, Any] = {}

    def emit(event: str, data: dict[str, Any]) -> None:
        # The writer of THIS graph, taken when its first node starts: the agent's own loop is a graph too, and a
        # status written from inside it must still reach this stream.
        (writer.get("w") or get_stream_writer())((event, data))

    turn = Turn(req, ctx, emit, stop=stop)

    def node(fn: Callable[[], None]) -> Callable[[State], State]:
        def run_node(state: State) -> State:
            writer.setdefault("w", get_stream_writer())
            fn()
            return {}

        return run_node

    g: Any = StateGraph(State)
    for name, fn in (("read", turn.read), ("loop", turn.loop), ("guard", turn.guard), ("save", turn.save)):
        g.add_node(name, node(fn))
    g.add_edge(START, "read")
    g.add_edge("read", "loop")
    g.add_edge("loop", "guard")
    g.add_edge("guard", "save")
    g.add_edge("save", END)
    return g.compile()


def run(req: SableTurnPayload, ctx: RunContext, stop: threading.Event | None = None) -> Iterator[Event]:
    for item in build(req, ctx, stop).stream({}, stream_mode="custom"):
        event, data = cast(Event, item)
        yield event, data


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeChat, FakeScenes

    ports = replace(Ports(), scenes=FakeScenes(), chat=FakeChat())
    req = SableTurnPayload(production_id=uuid4(), thread_id=uuid4(), actor_user_id=uuid4(), actor_name="Dee",
                           message="hi", user_message_id=uuid4())
    return build(req, RunContext(ports=ports))
