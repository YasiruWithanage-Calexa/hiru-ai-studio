"""The two ways the lab asks a model, behind one small interface (so the orchestrator is the same real and rehearsed).

    structured(...)   one answer held to a strict JSON schema: the workers (coverage planner, clip writer)
    step(...)         one turn of a tool-calling loop: the director

`OpenAIBackend` is the real one (the Responses API). It is built only by `run.py paid`, after a written yes: nothing else
in the lab imports a client. `Rehearsal` (rehearsal.py) answers from hand-written tables with no model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .money import Usage


@dataclass(frozen=True)
class Call:
    id: str
    name: str
    args: str  # the JSON text the model wrote


@dataclass
class Reply:
    id: str
    text: str = ""
    calls: list[Call] = field(default_factory=list)
    usage: Usage | None = None


class Backend(Protocol):
    def structured(self, *, system: str, user: str, schema: dict[str, Any], model: str, effort: str,
                   max_output: int) -> Reply: ...

    def step(self, *, system: str, items: list[dict[str, Any]], previous_id: str | None, tools: list[dict[str, Any]],
             model: str, effort: str, max_output: int) -> Reply: ...


def usage_of(resp: Any) -> Usage:
    u = getattr(resp, "usage", None)
    if u is None:
        return Usage(reported=False)
    status = getattr(resp, "status", "completed")
    return Usage(input_tokens=int(u.input_tokens or 0),
                 cached_tokens=int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0),
                 output_tokens=int(u.output_tokens or 0),
                 reasoning_tokens=int(getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0),
                 status="done" if status == "completed" else f"cut off ({status})")


class OpenAIBackend:
    """The Responses API, as `lab/cinematic/run.py` calls it, plus function tools for the director."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def structured(self, *, system: str, user: str, schema: dict[str, Any], model: str, effort: str,
                   max_output: int) -> Reply:
        resp = self.client.responses.create(
            model=model, instructions=system, input=user, max_output_tokens=max_output, reasoning={"effort": effort},
            text={"format": {"type": "json_schema", "name": schema["title"], "schema": schema, "strict": True}})
        return Reply(id=str(getattr(resp, "id", "")), text=str(getattr(resp, "output_text", "") or ""), usage=usage_of(resp))

    def step(self, *, system: str, items: list[dict[str, Any]], previous_id: str | None, tools: list[dict[str, Any]],
             model: str, effort: str, max_output: int) -> Reply:
        extra: dict[str, Any] = {"previous_response_id": previous_id} if previous_id else {}
        resp = self.client.responses.create(model=model, instructions=system, input=items, tools=tools,
                                            max_output_tokens=max_output, reasoning={"effort": effort}, **extra)
        calls = [Call(id=str(it.call_id), name=str(it.name), args=str(it.arguments))
                 for it in getattr(resp, "output", []) or [] if getattr(it, "type", "") == "function_call"]
        return Reply(id=str(resp.id), text=str(getattr(resp, "output_text", "") or ""), calls=calls, usage=usage_of(resp))
