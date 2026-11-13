"""zora_chat: one synchronous, STREAMED Zora turn over a scene's shot rows (plan/2026-11-13 §3.6).

Not a job, like the classic director chat: the API checks who is asking, stores their message, and proxies this
function's event stream back to the browser (`contracts.zora.events`). The graph is the turn's shape:

    read → in_code ─┬─ undo | redo (a revision, no model) ──────────────────────────────────┐
                    └─ conduct ─┬─ chat | clarify | cannot | nomodel | role ──────────────┤
                       (quick() │                                                        │
                       or the   └─ edit | craft | options → work ──────────────────────────┤
                       conductor)                                               reply ←───┘

`work` is the kernel, code's tasks, the author (variants on `options`), the board, the delivery check, the checks with
one repair, the risk rule and the save (or the card); `reply` the facts, the events and the reply written from them.

    run(req, ctx)      the events of one turn, in order
    act(req, ctx)      a person's click (accept, reject, use, undo, redo, lock, unlock): plain data in and out
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.director import TurnPayload
from contracts.zora.events import ZoraAction, ZoraActionResult
from contracts.zora.wire import WRITING_LANES
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.zora.zora_chat import actions
from hiru_ai.systems.zora.zora_chat.state import State
from hiru_ai.systems.zora.zora_chat.turn import Event, Turn


def build(req: TurnPayload, ctx: RunContext, **seams: Any) -> CompiledStateGraph[Any, Any, Any, Any]:
    def emit(event: str, data: dict[str, Any]) -> None:
        get_stream_writer()((event, data))

    turn = Turn(req, ctx, emit, **seams)

    def node(fn: Callable[[], None]) -> Callable[[State], State]:
        def run_node(state: State) -> State:
            fn()
            return {}

        return run_node

    def read(state: State) -> State:
        return {"route": "" if turn.read() else "gone"}

    def in_code(state: State) -> State:
        route = turn.in_code()
        turn.rec.lane = route
        return {"route": route}

    def conduct(state: State) -> State:
        return {"route": turn.conduct()}

    g: Any = StateGraph(State)
    g.add_node("read", read)
    g.add_node("in_code", in_code)
    g.add_node("conduct", conduct)
    g.add_node("restore", node(turn.restore))
    g.add_node("quiet", node(turn.quiet))
    g.add_node("work", node(turn.work))
    g.add_node("reply", node(turn.reply))
    g.add_edge(START, "read")
    g.add_conditional_edges("read", lambda s: END if s["route"] == "gone" else "in_code", ["in_code", END])
    g.add_conditional_edges("in_code", lambda s: "restore" if s["route"] in ("undo", "redo") else "conduct",
                            ["restore", "conduct"])
    g.add_conditional_edges("conduct", lambda s: "work" if s["route"] in WRITING_LANES else "quiet", ["work", "quiet"])
    for name in ("restore", "quiet", "work"):
        g.add_edge(name, "reply")
    g.add_edge("reply", END)
    return g.compile()


def run(req: TurnPayload, ctx: RunContext, **seams: Any) -> Iterator[Event]:
    """The turn's events. `seams` (`ask`, `say`) stand in for the models in tests (recorded answers)."""
    for item in build(req, ctx, **seams).stream({}, stream_mode="custom"):
        event, data = cast(tuple[str, dict[str, Any]], item)
        yield event, data


def act(req: ZoraAction, ctx: RunContext) -> ZoraActionResult:
    return actions.act(req, ctx)


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from dataclasses import replace
    from uuid import uuid4

    from hiru_ai.core.context import Ports
    from hiru_ai.core.fakes import FakeDirector, FakeScenes

    ports = replace(Ports(), scenes=FakeScenes(), director=FakeDirector())
    req = TurnPayload(production_id=uuid4(), scene_id=uuid4(), thread_id=uuid4(), actor_user_id=uuid4(),
                      actor_name="Dee", can_edit=True, can_edit_script=True, message="hi", user_message_id=uuid4())
    return build(req, RunContext(ports=ports))
