"""director_chat: one synchronous, STREAMED director turn (server-sent events out). Ported from
`director_chat/engine/turn.py` and `choice.py`.

Not a job: the API checks who is asking, stores their message, and proxies this function's event stream straight back to
the browser. The graph is the turn's shape:

    read -> conduct -> [ confirm | translate | reshape | edit | follow | options ] -> settle -> remember
         -> advise -> reply

`conduct` is the router (the `router` pattern's job: which flow a chat turn needs). Each node sends its events as it
goes through LangGraph's custom stream, so the person sees "Reading the scene", the plan, and the reply word by word.
The event shapes (`status | plan | delta | message | done | error`, `contracts.director`) are the engine's own.

    run(req, ctx)      the events of one turn, in order (an `error` event ends a turn whose scene is gone)
    choose(req, ctx)   a director chose a side of a disagreement or an option: plain data in and out, no model call
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.director import ChoicePayload, ChoiceResult, TurnPayload
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.director_chat import choice
from hiru_ai.systems.director_chat.state import State
from hiru_ai.systems.director_chat.turn import Event, Turn
from hiru_ai.systems.director_chat.view import DirectorView

BRANCHES = ("confirm", "translate", "reshape", "edit", "follow", "options")


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

    def conduct(state: State) -> State:
        return {"route": turn.conduct()}

    g: Any = StateGraph(State)
    g.add_node("read", read)
    g.add_node("conduct", conduct)
    for name, fn in (("confirm", turn.confirm), ("translate", turn.translate), ("reshape", turn.reshape),
                     ("edit", turn.edit), ("follow", turn.follow_up), ("options", turn.weigh_options),
                     ("settle", turn.settle), ("remember", turn.remember), ("advise", turn.advise),
                     ("reply", turn.reply)):
        g.add_node(name, node(fn))
    g.add_edge(START, "read")
    g.add_conditional_edges("read", lambda state: END if state["route"] == "gone" else "conduct", ["conduct", END])
    g.add_conditional_edges("conduct", lambda state: state["route"] if state["route"] in BRANCHES else "settle",
                            [*BRANCHES, "settle"])
    for name in BRANCHES:
        g.add_edge(name, "settle")
    for before, after in (("settle", "remember"), ("remember", "advise"), ("advise", "reply")):
        g.add_edge(before, after)
    g.add_edge("reply", END)
    return g.compile()


def run(req: TurnPayload, ctx: RunContext) -> Iterator[Event]:
    for item in build(req, ctx).stream({}, stream_mode="custom"):
        event, data = cast(tuple[str, dict[str, Any]], item)
        yield event, data


def choose(req: ChoicePayload, ctx: RunContext) -> ChoiceResult:
    return choice.apply_choice(req, DirectorView(ctx))


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
