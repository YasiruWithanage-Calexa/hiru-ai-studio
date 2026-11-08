"""plan/2026-11-08f §5: a tier with `responses: true` talks through OpenAI's Responses API with `previous_response_id`,
so a reasoning model's reasoning carries from one turn of a tool conversation to the next (the lab's way); and
`Agent.converse` answers the turns after the first on a `later_tier`.

The real `ChatOpenAI` runs on an httpx mock transport: the requests are checked byte for byte, no socket is opened.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from hiru_ai.core import llm as door
from hiru_ai.core.models import resolve
from hiru_ai.core.settings import AISettings, OpenAISettings

TOOL = {"type": "function", "function": {"name": "read_bin", "description": "Read the bin.",
                                         "parameters": {"type": "object", "properties": {}, "required": []}}}


def settings() -> AISettings:
    return AISettings(openai=OpenAISettings(api_key="sk-test"))  # type: ignore[arg-type]


def response(n: int) -> dict[str, Any]:
    return {
        "id": f"resp_{n}", "object": "response", "created_at": 1, "model": "gpt-5-2025-08-07", "status": "completed",
        "output": [{"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}", "name": "read_bin",
                    "arguments": "{}", "status": "completed"}],
        "parallel_tool_calls": True, "tool_choice": "required", "tools": [],
        "usage": {"input_tokens": 1000, "output_tokens": 300, "total_tokens": 1300,
                  "input_tokens_details": {"cached_tokens": 800}, "output_tokens_details": {"reasoning_tokens": 250}},
    }


class Wire:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=response(len(self.requests)))

    def body(self, n: int) -> dict[str, Any]:
        return json.loads(self.requests[n].content)  # type: ignore[no-any-return]


def test_raphaels_tiers_use_the_responses_api_and_the_others_do_not() -> None:
    for tier in ("raphael", "raphael_repair", "raphael_cinematic", "raphael_cinematic_repair"):
        t = resolve(tier, settings())
        assert t.responses and (t.model, t.effort) == ("gpt-5", "high"), tier  # the lab's, until the cost lab
        assert t.fallbacks == ()
    assert not resolve("high", settings()).responses and not resolve("jonathan", settings()).responses


def test_the_second_turn_sends_previous_response_id_and_only_the_new_tool_result() -> None:
    wire = Wire()
    model: Any = door.get_llm("raphael", settings=settings(), http_client=wire.client)
    bound = model.bind_tools([TOOL], tool_choice="required").bind(max_tokens=48_000)
    thread: list[Any] = [SystemMessage("You plan shots."), HumanMessage("Plan this scene.")]
    first = bound.invoke(thread)
    assert isinstance(first, AIMessage) and first.tool_calls and first.response_metadata.get("id") == "resp_1"
    thread += [first, ToolMessage(content="2 clips.", tool_call_id=first.tool_calls[0]["id"])]
    bound.invoke(thread)

    one, two = wire.body(0), wire.body(1)
    assert wire.requests[0].url.path.endswith("/responses")
    assert one["reasoning"] == {"effort": "high"} and one["max_output_tokens"] == 48_000
    assert "previous_response_id" not in one
    assert two["previous_response_id"] == "resp_1"
    # only what came after the last reply is sent: the tool's result, not the system prompt or the first message
    assert [item.get("type") for item in two["input"]] == ["function_call_output"]
    assert first.usage_metadata and first.usage_metadata["input_token_details"]["cache_read"] == 800
    assert first.usage_metadata["output_token_details"]["reasoning"] == 250


def test_the_later_tier_answers_every_turn_after_the_first(monkeypatch: Any) -> None:
    """A repair turn at a lower effort: the first request says high, the second says low."""
    monkeypatch.setenv("OPENAI__EFFORT_RAPHAEL_REPAIR", "low")
    monkeypatch.setenv("OPENAI__API_KEY", "sk-test")
    from hiru_ai.core.settings import get_settings

    get_settings.cache_clear()
    wire = Wire()
    real = door._chat

    def chat(tier: Any, cfg: Any, callbacks: Any, http_client: Any) -> Any:
        return real(tier, cfg, callbacks, wire.client)

    monkeypatch.setattr(door, "_chat", chat)
    try:
        from hiru_ai.core import agents

        agent = agents.build("raphael_planner")
        calls: list[int] = []

        def call_tool(name: str, raw: str) -> str:
            calls.append(len(calls) + 1)
            return "Report: 1 blocking fault(s)."

        done = agent.converse(
            {"opening": "Plan this scene.", "scene": {"blocks": []}}, tools=[TOOL], call_tool=call_tool,
            finished=lambda: len(calls) >= 2, max_turns=3, later_tier="raphael_repair",
        )
    finally:
        get_settings.cache_clear()
    assert done.stopped == "finished" and done.turns == 2
    assert wire.body(0)["reasoning"] == {"effort": "high"}
    assert wire.body(1)["reasoning"] == {"effort": "low"} and wire.body(1)["previous_response_id"] == "resp_1"
