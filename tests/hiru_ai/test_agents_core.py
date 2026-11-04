"""The agent builders: what goes on the wire, what is counted, what degrades, and the react tool loop (Phase 4).

The structured agents run on the real `ChatOpenAI` over an httpx mock transport (no socket, no key), so the checks cover
the request bytes OpenAI would receive. The react loop runs on a scripted chat model that calls a tool.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.errors import GraphInterrupt  # noqa: F401  (hitl pauses a graph by interrupting)
from pydantic import Field

from hiru_ai.core import agents, llm
from hiru_ai.core import registry as registry_mod
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.fakes import FakeSearch
from hiru_ai.core.settings import AISettings, OpenAISettings

USAGE = {"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940,
         "prompt_tokens_details": {"cached_tokens": 512}}
REG = registry_mod.default()


def completion(content: str) -> dict[str, Any]:
    return {"id": "c1", "object": "chat.completion", "created": 1, "model": "gpt-5-mini-2026",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": USAGE}


class Wire:
    """A mock OpenAI: remembers the request bodies, answers from a script."""

    def __init__(self, *replies: dict[str, Any]) -> None:
        self.replies, self.bodies = list(replies), []

    def client(self) -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            return httpx.Response(200, json=completion(json.dumps(self.replies.pop(0))))

        return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Models on (a key is set) but the HTTP client is the mock's: the real ChatOpenAI, no network."""
    wire = Wire()
    settings = AISettings(openai=OpenAISettings(api_key="sk-test"))  # type: ignore[arg-type]
    real = llm._chat

    def chat(tier: Any, s: Any, callbacks: Any, http_client: Any) -> Any:
        return real(tier, s, callbacks, wire.client())

    monkeypatch.setattr(llm, "_chat", chat)
    monkeypatch.setattr(llm, "get_settings", lambda: settings)
    return wire


def run(ident: str, inp: dict[str, Any], keyed_wire: Wire, reply: dict[str, Any], ctx: RunContext | None = None) -> Any:
    keyed_wire.replies.append(reply)
    return agents.Agent(REG, ident).run(inp, ctx or RunContext(strict=True))


def test_a_structured_agent_sends_a_strict_schema_and_the_messages_it_built(keyed: Wire):
    rows: list[dict[str, Any]] = []
    ctx = RunContext(strict=True, usage_sink=rows.append, job_id=uuid4(), production_id=uuid4())
    out = run("advisor", {"charter": "Cut early.", "summary": "S02 -> CU", "scene_text": "S01 WIDE"}, keyed,
              {"agrees": False, "view": "Cut sooner."}, ctx)
    assert (out.agrees, out.view) == (False, "Cut sooner.")
    body = keyed.bodies[0]
    assert body["model"] == "gpt-5-mini" and body["reasoning_effort"] == "low"  # the medium tier
    system, user = body["messages"]
    agent = agents.Agent(REG, "advisor")
    assert system["content"] == agent.prompt.text and user["content"] == agent.messages(
        {"charter": "Cut early.", "summary": "S02 -> CU", "scene_text": "S01 WIDE"})[1]
    fmt = body["response_format"]["json_schema"]
    assert fmt["strict"] is True and set(fmt["schema"]["properties"]) == {"agrees", "view"}
    assert [(r["phase"], r["input_tokens"], r["cached_input_tokens"], r["output_tokens"]) for r in rows] == [
        ("director.advisor", 900, 512, 40)]
    assert rows[0]["job_id"] == str(ctx.job_id) and rows[0]["production_id"] == str(ctx.production_id)


def test_the_shot_writers_schema_comes_from_the_clip_yaml_and_is_named(keyed: Wire):
    agent = agents.Agent(REG, "shot_writer")
    out = run("shot_writer", {"production": "<production/>", "scene": "<scene/>"}, keyed, {"shots": []})
    assert out.shots == []
    fmt = keyed.bodies[0]["response_format"]["json_schema"]
    assert fmt["name"] == "scene_design" and fmt["strict"] is True
    assert fmt["schema"]["properties"]["shots"]["items"]["properties"]["recommendation"]["properties"]["lens"][
        "enum"] == ["28mm", "35mm", "50mm", "85mm"]
    assert agent.wire_schema()["title"] == "scene_design"


def test_a_vision_agent_sends_the_picture_at_low_detail_on_the_vision_tier(keyed: Wire):
    run("frame_inspector", {"image_b64": "iVBORw0KGgo=", "seen": ["Anudi"], "frame": "at the window"}, keyed,
        {"main_people": 1, "unexpected_person": False, "matches": True, "problems": []})
    body = keyed.bodies[0]
    assert body["model"] == "gpt-5-mini" and "reasoning_effort" not in body
    parts = body["messages"][1]["content"]
    assert [p["type"] for p in parts] == ["text", "image_url"]
    assert parts[1]["image_url"] == {"url": "data:image/png;base64,iVBORw0KGgo=", "detail": "low"}


def test_an_agent_with_a_fallback_degrades_and_one_without_says_why(monkeypatch: pytest.MonkeyPatch):
    inp = {"charter": "x", "summary": "y", "scene_text": "z"}
    assert agents.Agent(REG, "advisor").run(inp, RunContext()).agrees is True  # no key: the fallback agrees
    with pytest.raises(ModelUnavailable):  # the conductor has none: its system reads the message by rules
        agents.Agent(REG, "conductor").run({"plan_text": "S01", "message": "hi"}, RunContext())
    from hiru_ai.core.testing import ScriptedChatModel

    with llm.use_models(ScriptedChatModel(replies=[RuntimeError("503")])):  # a failed call degrades too
        assert agents.Agent(REG, "advisor").run(inp, RunContext()).view == ""


def test_a_structured_agent_that_may_not_write_dialogue_cannot_hand_back_a_changed_line():
    """language_guard rides on every agent without writes_dialogue (the translator alone is exempt)."""
    from hiru_ai.core.errors import DialogueChanged
    from hiru_ai.core.middleware import ModelCall, build, run_chain

    call = ModelCall(component="agent:editor", phase="p", tier="high", system="s", user="u",
                     lines_before={"l1": "Hello"}, lines_after=lambda r: r)
    chain = build(["static_first"], writes_dialogue=False)
    with pytest.raises(DialogueChanged):
        run_chain(chain, call, RunContext(), lambda c: {"l1": "Hallo"})
    assert run_chain(build([], writes_dialogue=True), call, RunContext(), lambda c: {"l1": "Hallo"}) == {"l1": "Hallo"}


# ── react ──────────────────────────────────────────────────────────────────────────────────


class ToolCaller(BaseChatModel):
    """Plays a tool loop: calls `veo_fit`, then answers through the structured-output tool."""

    script: list[AIMessage] = Field(default_factory=list)
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "tool-caller"

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        return self


def react_agent(monkeypatch: pytest.MonkeyPatch, **update: Any) -> agents.Agent:
    """A real agent (the advisor) turned into a tool loop for the test: tools and knowledge come from its manifest."""
    agent = agents.Agent(REG, "advisor")
    agent.manifest = agent.manifest.model_copy(update={"shape": "react", "tools": ["veo_fit"], **update})
    return agent


def test_a_react_agent_calls_its_tools_with_the_scope_of_the_run_and_answers_in_its_output_type(
        monkeypatch: pytest.MonkeyPatch):
    agent = react_agent(monkeypatch)
    seen_ctx: list[Any] = []
    from hiru_ai.tools.veo_fit import tool as veo

    real = veo.run
    monkeypatch.setattr(veo, "run", lambda args, ctx: (seen_ctx.append(ctx), real(args, ctx))[1])
    model = ToolCaller(script=[
        AIMessage(content="", tool_calls=[{"name": "veo_fit", "args": {"words": 12}, "id": "t1"}]),
        AIMessage(content="", tool_calls=[{"name": "Output", "args": {"agrees": False, "view": "12 words need 6 s."},
                                            "id": "t2"}])])
    ctx = RunContext(production_id=uuid4(), strict=True)
    with llm.use_models(model):
        out = agent.run({"charter": "x", "summary": "y", "scene_text": "z"}, ctx)
    assert (out.agrees, out.view) == (False, "12 words need 6 s.")
    assert seen_ctx and seen_ctx[0].production_id == ctx.production_id, "the tool read the run's scope, not the model's"
    tool_turn = [m for m in model.seen[1] if getattr(m, "type", "") == "tool"]
    assert tool_turn and "6" in str(tool_turn[0].content), "the model saw the tool's answer"


def test_a_react_agent_may_search_only_the_knowledge_bases_it_lists(monkeypatch: pytest.MonkeyPatch):
    agent = react_agent(monkeypatch, tools=["search_kb"], knowledge=["craft"])
    search = FakeSearch(chunks=[{"id": str(uuid4()), "content": "Shot size.", "corpus": "craft"}])
    model = ToolCaller(script=[
        AIMessage(content="", tool_calls=[{"name": "search_kb", "args": {"query": "shot size"}, "id": "t1"}]),
        AIMessage(content="", tool_calls=[{"name": "Output", "args": {"agrees": True, "view": ""}, "id": "t2"}])])
    ctx = RunContext(production_id=uuid4(), strict=True, ports=Ports(search=search),
                     corpora=("craft", "production_docs"))  # the run allows more than the agent lists
    with llm.use_models(model):
        agent.run({"charter": "x", "summary": "y", "scene_text": "z"}, ctx)
    assert search.asked[0]["corpora"] == ["craft"]


def test_hitl_stops_a_writing_tool_for_a_person_and_a_reading_tool_runs(monkeypatch: pytest.MonkeyPatch):
    from hiru_ai.core.middleware import react

    writes = react.build(["hitl"], tier="high", gated=["change_propose"])
    assert len(writes) == 1 and type(writes[0]).__name__ == "HumanInTheLoopMiddleware"
    assert react.build(["hitl"], tier="high", gated=[]) == [], "nothing to gate"
    assert [type(m).__name__ for m in react.build(["retry"], tier="high")] == ["ModelRetryMiddleware"]
    assert react.build(["fallback"], tier="high") == [], "no tier lists a fallback today"


def test_hiru_ai_run_agent_shows_the_messages_and_answers_a_scripted_case(tmp_path: Any,
                                                                          capsys: pytest.CaptureFixture[str]):
    from hiru_ai.cli.main import main

    case = tmp_path / "case.json"
    case.write_text(json.dumps({"input": {"charter": "Cut early.", "summary": "S02 -> CU", "scene_text": "S01"},
                                "reply": {"agrees": False, "view": "Cut sooner."}}), encoding="utf-8")
    assert main(["run", "agent", "advisor", "--input", str(case)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["tier"], shown["phase"]) == ("medium", "director.advisor")
    assert shown["output"]["view"] == "Cut sooner."
    assert shown["user"].startswith("<your_style>\nCut early.") and len(shown["prompt_sha"]) == 12
    case.write_text(json.dumps({"input": {"charter": "c", "summary": "s", "scene_text": "t"}}), encoding="utf-8")
    assert main(["run", "agent", "advisor", "--input", str(case)]) == 0  # no reply: the messages only, nothing sent
    assert "output" not in json.loads(capsys.readouterr().out)
