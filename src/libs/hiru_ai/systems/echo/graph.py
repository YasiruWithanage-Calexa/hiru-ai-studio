"""echo: pending → running → (event) → done, with the result written once. Ported from `echo_service/app/handler.py`.

The template for a system. `run(payload, ctx)` is what a function's thin handler calls:

    1. `jobs.check(payload)`: a finished (or stale) delivery is skipped, because Cloud Tasks re-delivers;
    2. mark the job running, run the graph (`build`), finish through the job port;
    3. an exception is the handler's to turn into a failed job (200) or a retry (500).

The graph holds what the system DECIDES (here one node); the job contract stays in `run`, which every system shares.
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from contracts.jobs import DispatchPayload, JobEventType, JobStatus
from hiru_ai.core.context import RunContext
from hiru_ai.core.registry import Registry
from hiru_ai.systems.echo.state import State

AGENT = "echo"


def build(ctx: RunContext, payload: DispatchPayload) -> CompiledStateGraph[Any, Any, Any, Any]:
    def echo(state: State) -> State:
        message = state.get("message", "")
        ctx.need("jobs").event(payload.job_id, JobEventType.PROGRESS, {"text": f"Echoing {message!r}"}, agent=AGENT)
        return {"result": {"echo": message, "actor_user_id": str(payload.actor_user_id)}}

    g: Any = StateGraph(State)
    g.add_node("echo", echo)
    g.add_edge(START, "echo")
    g.add_edge("echo", END)
    return g.compile()


def run(payload: DispatchPayload, ctx: RunContext) -> dict[str, Any]:
    jobs = ctx.need("jobs")
    skip = jobs.check(payload)
    if skip:
        return {"skipped": skip}
    jobs.set(payload.job_id, JobStatus.RUNNING)
    result: dict[str, Any] = build(ctx, payload).invoke({"message": str(payload.state.get("message", ""))})["result"]
    jobs.finish(payload, result)
    return result


def blank(registry: Registry | None = None) -> CompiledStateGraph[Any, Any, Any, Any]:
    """The graph with nothing to run, for drawing and for the generated contract tests."""
    from uuid import uuid4

    from contracts.jobs import JobKind

    return build(RunContext(), DispatchPayload(job_id=uuid4(), kind=JobKind.ECHO, actor_user_id=uuid4()))
