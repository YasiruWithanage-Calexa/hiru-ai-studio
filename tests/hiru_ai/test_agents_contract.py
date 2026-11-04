"""Generated contract tests for every agent in the registry (plan §5.8, Phase 4 exit).

Nothing is listed by hand: a new agent folder is picked up at once, and an agent that breaks the contract fails under
its own name. For each agent: it builds, its system prompt is static text that comes first, its user message carries
the per-item data, its Output schema is one the model door can send strictly, its eval cases run against a scripted
model and give the expected answer, and with no model it takes its fallback.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from hiru_ai.core import agents, llm
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable
from hiru_ai.core.middleware.base import MISSING
from hiru_ai.core.registry import Component, default
from hiru_ai.core.testing import ScriptedChatModel

REGISTRY = default()
AGENTS = [pytest.param(c, id=c.manifest.id) for (k, _), c in sorted(REGISTRY.components.items()) if k == "agent"]


def cases(comp: Component, form: str = "base") -> list[dict[str, Any]]:
    """The agent's eval cases for one form (`base` = the single call, `tools` = its `with_tools` form)."""
    out: list[dict[str, Any]] = []
    for path in sorted((comp.folder / "evals").glob("*.yaml")):
        out += yaml.safe_load(path.read_text(encoding="utf-8"))
    return [c for c in out if c.get("variant") in (None, form)]


CASES = [pytest.param(p.values[0], case, id=f"{p.values[0].manifest.id}/{case['name']}")
         for p in AGENTS for case in cases(p.values[0])]


def subset(expected: Any, got: Any) -> bool:
    """`expected` is contained in `got`: every key of a mapping, every item of a list in order, every value equal."""
    if isinstance(expected, dict):
        return isinstance(got, dict) and all(k in got and subset(v, got[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(got, list) and len(expected) == len(got)
                and all(subset(a, b) for a, b in zip(expected, got, strict=True)))
    return bool(expected == got)


def test_there_are_agents_to_check():
    assert AGENTS, "Phase 4 ports the agents; none were found"


@pytest.mark.parametrize("comp", AGENTS)
def test_the_agent_builds_with_typed_seams_and_a_static_prompt(comp: Component):
    agent = agents.Agent(REGISTRY, comp.manifest.id)
    assert issubclass(agent.input_cls, BaseModel) and issubclass(agent.output_cls, BaseModel)
    assert agent.prompt.text.strip()
    assert agent.phase and agent.manifest.model


@pytest.mark.parametrize("comp", AGENTS)
def test_the_output_schema_is_one_the_door_can_send_strictly(comp: Component):
    """OpenAI strict mode: every object closed, every property required. A defaulted field would be dropped from
    `required` and refused on the wire, so Output models declare none."""
    agent = agents.Agent(REGISTRY, comp.manifest.id)

    def check(node: Any, where: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                props = set(node.get("properties", {}))
                assert set(node.get("required", [])) == props, f"{where}: every property must be required"
                assert node.get("additionalProperties") is False, f"{where}: objects must be closed"
            for key, value in node.items():
                check(value, f"{where}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                check(value, f"{where}[{i}]")

    from langchain_core.utils.function_calling import convert_to_openai_function

    wire = agent.wire_schema()
    schema = wire if isinstance(wire, dict) else convert_to_openai_function(wire, strict=True)["parameters"]
    check(schema, agent.id)


@pytest.mark.parametrize("comp", AGENTS)
def test_every_agent_has_two_eval_cases_that_name_their_reply(comp: Component):
    found = cases(comp)
    assert len(found) >= 2
    for case in found:
        assert case.get("input") is not None and ("reply" in case or case.get("model") == "unavailable"), case["name"]


@pytest.mark.parametrize(("comp", "case"), CASES)
def test_an_eval_case_runs_against_a_scripted_model(comp: Component, case: dict[str, Any]):
    agent = agents.Agent(REGISTRY, comp.manifest.id)
    inp = agent.input_cls.model_validate(case["input"])
    system, user = agent.messages(inp)
    assert system.startswith(agent.prompt.text) and user.strip(), "a static system prompt, per-item data in the user"
    ctx = RunContext(strict=True)  # static_first raises instead of logging
    if case.get("model") == "unavailable":
        got = agent.run(inp, ctx)  # no key in tests: the door says so and absent_safe takes the fallback
    else:
        model = ScriptedChatModel(replies=[case["reply"]])
        with llm.use_models(model):
            got = agent.run(inp, ctx)
        sent = model.calls[0]
        sent_user = sent[1].content
        if isinstance(sent_user, list):  # a vision call: the text part, then the pictures
            assert [p["type"] for p in sent_user] == ["text", *["image_url"] * (len(sent_user) - 1)]
            sent_user = sent_user[0]["text"]
        assert sent[0].content == system and sent_user == user
    assert isinstance(got, agent.output_cls)
    assert subset(case.get("expect", {}), got.model_dump(mode="json")), f"{case['name']}: {got!r}"


@pytest.mark.parametrize("comp", AGENTS)
def test_without_a_model_an_agent_with_a_fallback_answers_and_one_without_says_so(comp: Component):
    agent = agents.Agent(REGISTRY, comp.manifest.id)
    inp = agent.input_cls.model_validate(next(c for c in cases(comp))["input"])
    has_fallback = agent.prepare(inp).fallback is not MISSING
    if "absent_safe" in agent.manifest.middleware and has_fallback:
        assert isinstance(agent.run(inp, RunContext()), agent.output_cls)
    else:
        with pytest.raises(ModelUnavailable):
            agent.run(inp, RunContext())


@pytest.mark.parametrize("comp", AGENTS)
def test_an_agent_that_is_not_the_translator_cannot_change_a_spoken_line(comp: Component):
    assert comp.manifest.writes_dialogue == (comp.manifest.id == "translator")  # type: ignore[union-attr]


def test_prompt_files_are_the_only_place_a_system_prompt_lives():
    for comp in (p.values[0] for p in AGENTS):
        for path in (Path(comp.folder) / "agent.py", Path(comp.folder) / "schema.py"):
            text = path.read_text(encoding="utf-8")
            assert "SYSTEM =" not in text and "_SYSTEM" not in text, f"{path}: keep the prompt in prompts/system.md"


# ── the `with_tools` form of an agent (plan/2026-11-04 §8) ───────────────────────────────────────────────────────────

TOOL_AGENTS = [p for p in AGENTS if p.values[0].manifest.with_tools is not None]  # type: ignore[union-attr]


def test_the_four_agents_of_phase_2_have_a_tools_form():
    assert {p.values[0].manifest.id for p in TOOL_AGENTS} >= {"chat_answerer", "options_writer", "translator",
                                                              "shot_critic"}


@pytest.mark.parametrize("comp", TOOL_AGENTS)
def test_the_tools_form_is_a_react_agent_with_its_own_prompt_and_a_stable_sorted_tool_block(comp: Component):
    plain = agents.Agent(REGISTRY, comp.manifest.id, with_tools=False)
    tools = agents.Agent(REGISTRY, comp.manifest.id, with_tools=True)
    assert plain.manifest.shape != "react" and not plain.uses_tools
    assert tools.manifest.shape == "react" and tools.uses_tools and tools.prompt.text != plain.prompt.text
    names = [t.name for t in tools.tools()]
    assert names == sorted(names) and 1 <= len(names) <= 8
    assert tools.tool_block() == agents.Agent(REGISTRY, comp.manifest.id, with_tools=True).tool_block()
    assert tools.output_cls is plain.output_cls  # the callers get the same answer either way


@pytest.mark.parametrize("comp", TOOL_AGENTS)
def test_the_tools_form_is_off_until_agent_tools_names_it(comp: Component, monkeypatch: pytest.MonkeyPatch):
    from hiru_ai.core.settings import get_settings

    ident = comp.manifest.id
    assert not agents.Agent(REGISTRY, ident).uses_tools
    monkeypatch.setenv("AGENT_TOOLS", f"other, {ident}")
    get_settings.cache_clear()
    assert agents.Agent(REGISTRY, ident).uses_tools
    assert not agents.Agent(REGISTRY, ident, with_tools=False).uses_tools  # an explicit choice beats the setting


@pytest.mark.parametrize("comp", TOOL_AGENTS)
def test_the_tools_form_passes_its_scripted_cases_and_has_a_case_that_calls_a_tool_and_one_that_must_not(
        comp: Component):
    from hiru_ai.cli import evals

    found = cases(comp, "tools")
    assert any(c.get("tool_calls") for c in found), "a case that needs a lookup"
    assert any(c.get("expect_no_tools") for c in found), "a case that must not make one"
    results = evals.run_agent(REGISTRY, comp.manifest.id, tools=True)
    assert results and all(r.passed for r in results), [(r.case, r.detail) for r in results if not r.passed]
