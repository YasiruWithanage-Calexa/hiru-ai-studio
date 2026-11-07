"""zora_chat: one synchronous, STREAMED Zora turn over a scene's stored Jonathan plan (plan/2026-11-06e §3, Phase 4).

Not a job, like the classic director chat: the API checks who is asking, stores their message, and proxies this
function's event stream back to the browser (`contracts.zora.events`). The graph is the turn's shape:

    read → in_code ─┬─ undo | redo | confirm ───────────────────────────────────────────────┐
                    ├─ a suggestion (a button: no router) → edit ───────────────────────────┤
                    └─ conduct → [ chat | clarify | cannot | translate | shape | nomodel ] ──┤
                                 [ edit | craft | options ] → edit ─────────────────────────┤
                                                                         settle → reply ←───┘

`edit` is the kernel, the dependency graph, the re-cut guard, the author (variants on `options`), the board and the
delivery check; `settle` the planner's gate with its repair passes and the save; `reply` the ledger, the events and the
reply written from them.

    run(req, ctx)      the events of one turn, in order
    act(req, ctx)      a person's click (use a proposal, undo, redo, lock, unlock): plain data in and out, no model
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.director import TurnPayload
from contracts.zora.events import ZoraAction, ZoraActionResult
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.zora.zora_chat import actions
from hiru_ai.systems.zora.zora_chat.state import State
from hiru_ai.systems.zora.zora_chat.turn import Event, Turn

QUIET = ("chat", "clarify", "cannot", "translate", "shape", "nomodel")
WRITING = ("edit", "craft", "options")
IN_CODE = ("undo", "redo", "confirm")


def build(req: TurnPayload, ctx: RunContext) -> CompiledStateGraph[Any, Any, Any, Any]:
    def emit(event: str, data: dict[str, Any]) -> None:
        get_stream_writer()((event, data))

    turn = Turn(req, ctx, emit)

    def node(fn: Callable[[], None]) -> Callable[[State], State]:
        def run_node(state: State) -> State:
            fn()
            return {}

        return run_node

    def read(state: State) -> State:
        return {"route": "" if turn.read() else "gone"}

    def in_code(state: State) -> State:
        route = turn.in_code()
        turn.st.lane = route
        return {"route": route}

    def conduct(state: State) -> State:
        return {"route": turn.conduct()}

    def quiet(state: State) -> State:
        lane = turn.st.lane
        if lane == "cannot":
            turn.cannot()
        elif lane == "translate":
            turn.translate()
        elif lane == "shape":
            turn.shape()
        return {}

    g: Any = StateGraph(State)
    g.add_node("read", read)
    g.add_node("in_code", in_code)
    g.add_node("conduct", conduct)
    g.add_node("restore", node(turn.restore))
    g.add_node("confirm", node(turn.confirm))
    g.add_node("quiet", quiet)
    g.add_node("edit", node(turn.edit))
    g.add_node("settle", node(turn.settle))
    g.add_node("reply", node(turn.reply))
    g.add_edge(START, "read")
    g.add_conditional_edges("read", lambda s: END if s["route"] == "gone" else "in_code", ["in_code", END])
    g.add_conditional_edges("in_code", lambda s: {"undo": "restore", "redo": "restore", "confirm": "confirm",
                                                  "suggested": "edit"}.get(s["route"], "conduct"),
                            ["restore", "confirm", "conduct", "edit"])
    g.add_conditional_edges("conduct", lambda s: "edit" if s["route"] in WRITING else "quiet", ["edit", "quiet"])
    for name in ("restore", "confirm", "quiet"):
        g.add_edge(name, "reply")
    g.add_edge("edit", "settle")
    g.add_edge("settle", "reply")
    g.add_edge("reply", END)
    return g.compile()


def run(req: TurnPayload, ctx: RunContext) -> Iterator[Event]:
    for item in build(req, ctx).stream({}, stream_mode="custom"):
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
