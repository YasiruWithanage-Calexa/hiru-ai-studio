"""`hiru-ai eval`: every agent's eval cases, run and scored (plan/2026-11-03 Phase 8, plan/2026-11-04 Phase 0).

    hiru-ai eval                      every agent, each case answered by its scripted reply: the structure gate (CI)
    hiru-ai eval translator           one agent
    hiru-ai eval translator --live    the real model answers the case INPUTS (costs money: only a person runs it)
    hiru-ai eval translator --live --prompt other.md
                                      the same cases through another system prompt: A/B two versions of a prompt
    hiru-ai eval chat_answerer --ab old.yaml,current
                                      the same cases through two manifests (a file, or `current` = the one in the tree):
                                      score, tokens, model calls, tool calls and tool errors side by side
    hiru-ai eval chat_answerer --ab base,tools --live
                                      the single call against its `with_tools` form (plan/2026-11-04 §8): the gate an
                                      agent passes before AGENT_TOOLS names it
    hiru-ai eval chat_answerer --tools
                                      only the `with_tools` form

A case passes when its `expect` is contained in the agent's answer. Scripted, the answer is the case's own reply, so a
pass says the agent builds, sends what it should and cleans the answer as it should; live, it says the model still gets
the case right. The pass rate of each agent is printed with what it cost (input / cached / output tokens, model calls,
tool calls, tool errors), and the command fails when any case does not pass.

A `react` agent's case can script the tool calls its model makes, so CI checks the loop without a model:

    - name: asks about a shot
      input: { ... }
      fixtures: { ... }                       # the in-memory ports the tools read (core.fakes.ports_from)
      production_id: ...   scene_id: ...   said: "..."   corpora: [...]
      tool_calls:                             # one per model round, in order
        - { name: shot_read, args: { shot: S03 }, expect: { shot: S03 } }   # expect: a subset of the tool's answer
      reply: { ... }                          # then the final answer
      expect: { ... }
      expect_no_tools: true                   # instead of tool_calls: the agent must answer without calling any tool
      variant: tools                          # only the `with_tools` form runs it (`base`: only the single call)
      example: shot_read                      # instead of fixtures: the world of that tool's examples/basic.json
                                              # (production_id, scene_id, said, corpora, fixtures; the case's own win)
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from langchain_core.messages import AIMessage

from hiru_ai.core import agents, llm
from hiru_ai.core import manifest as mf
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import ports_from
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.registry import Component, Registry
from hiru_ai.core.testing import RoutedChatModel, ScriptedChatModel
from hiru_ai.core.usage import UsageRow


@dataclasses.dataclass
class Result:
    agent: str
    case: str
    passed: bool
    detail: str = ""
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0


def contained(expected: Any, got: Any) -> bool:
    """`expected` is contained in `got`: every key of a mapping, every item of a list in order, every value equal."""
    if isinstance(expected, dict):
        return isinstance(got, dict) and all(k in got and contained(v, got[k]) for k, v in expected.items())
    if isinstance(expected, list):
        return (isinstance(got, list) and len(expected) == len(got)
                and all(contained(a, b) for a, b in zip(expected, got, strict=True)))
    return bool(expected == got)


def cases_of(reg: Registry, ident: str, *, tools: bool = False, every: bool = False) -> list[dict[str, Any]]:
    """The agent's cases for one form: those with no `variant` run in both, `variant: tools` / `base` in one. `every`
    = all of them, for a live A/B: the inputs are valid for both forms, only the scripted replies differ."""
    out: list[dict[str, Any]] = []
    for path in sorted((reg.get("agent", ident).folder / "evals").glob("*.yaml")):
        out += yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return out if every else [c for c in out if c.get("variant") in (None, "tools" if tools else "base")]


def with_example(case: dict[str, Any]) -> dict[str, Any]:
    """The case over the world of a tool's example (`example: <tool id>`), so a scripted tool loop does not repeat a
    fixture dozens of lines long; what the case itself names wins."""
    if not case.get("example"):
        return case
    from hiru_ai.core.testing import example_of

    base = example_of(str(case["example"]))
    return {**{k: v for k, v in base.items() if k != "args"}, **case}


def _context(case: dict[str, Any], rows: list[UsageRow]) -> RunContext:
    production, scene = case.get("production_id"), case.get("scene_id")
    return RunContext(
        production_id=UUID(production) if production else None, scene_id=UUID(scene) if scene else None,
        said=str(case.get("said") or ""), corpora=tuple(case.get("corpora") or ()),
        ports=ports_from(case.get("fixtures") or {}), usage_sink=rows.append, usage_detail=True)


def _script(agent: agents.Agent, case: dict[str, Any]) -> list[Any]:
    """The model's replies for a case that scripts tool calls: one tool call per round, then the answer as the call to
    the structured-output tool LangChain gives a `react` agent (named after the Output class)."""
    replies: list[Any] = [
        AIMessage(content="", tool_calls=[{"name": c["name"], "args": c.get("args") or {}, "id": f"call-{n}",
                                           "type": "tool_call"}])
        for n, c in enumerate(case.get("tool_calls") or [])]
    reply = case["reply"]
    if isinstance(reply, str):  # a text agent's cases give the reply as the text
        reply = {"text": reply}
    replies.append(AIMessage(content="", tool_calls=[{"name": agent.output_cls.__name__, "args": reply,
                                                      "id": "final", "type": "tool_call"}]))
    return replies


def _check_tools(case: dict[str, Any], ctx: RunContext) -> str:
    """Why the case's tool expectations failed, or ''."""
    events = ctx.tool_events
    calls = case.get("tool_calls") or []
    if case.get("expect_no_tools") and events:
        return f"called {', '.join(e.tool for e in events)}, but the case says it needs no tool"
    if calls and [e.tool for e in events] != [c["name"] for c in calls]:
        return f"called {[e.tool for e in events]}, expected {[c['name'] for c in calls]}"
    bad = [e.tool for e in events if e.error]
    return f"tool errors: {', '.join(bad)}" if bad and not case.get("allow_tool_errors") else ""


def run_agent(reg: Registry, ident: str, *, live: bool = False, prompt: Path | None = None,
              tools: bool = False, every: bool = False) -> list[Result]:
    agent = agents.Agent(reg, ident, with_tools=tools)
    if prompt is not None:  # the same agent, another system prompt: the other side of an A/B
        agent.prompt = Prompt.load(prompt)
    label = f"{ident} (tools)" if tools else ident
    results = []
    for case in (with_example(c) for c in cases_of(reg, ident, tools=tools, every=every)):
        name = str(case.get("name"))
        rows: list[UsageRow] = []
        ctx = _context(case, rows)
        try:
            inp = agent.input_cls.model_validate(case["input"])
            scripted_tools = agent.manifest.shape == "react" and not live
            if live:
                got = agent.run(inp, ctx)
            elif case.get("model") == "unavailable":  # no reply left: a model out of reach, never the real one
                with llm.use_models(ScriptedChatModel(replies=[])):
                    got = agent.run(inp, ctx)
            elif scripted_tools:
                model = RoutedChatModel(routes={"all": _script(agent, case)}, choose=lambda m: "all")
                with llm.use_models(model):
                    got = agent.run(inp, ctx)
            else:
                with llm.use_models(ScriptedChatModel(replies=[case["reply"]])):
                    got = agent.run(inp, ctx)
            ok = contained(case.get("expect", {}), got.model_dump(mode="json"))
            detail = "" if ok else f"got {got.model_dump(mode='json')}"
            if why := _check_tools(case, ctx):
                ok, detail = False, f"{detail}; {why}".lstrip("; ")
            for call, event in zip(case.get("tool_calls") or [], ctx.tool_events, strict=False):
                wanted = call.get("expect")
                if wanted and event.error:
                    ok, detail = False, f"{detail}; {call['name']} answered an error".lstrip("; ")
            results.append(_counted(Result(label, name, ok, detail), rows, ctx))
        except Exception as exc:  # a case that cannot run is a failed case, named
            results.append(_counted(Result(label, name, False, f"{type(exc).__name__}: {exc}"), rows, ctx))
    return results


def _counted(result: Result, rows: list[UsageRow], ctx: RunContext) -> Result:
    result.input_tokens = sum(int(r.get("input_tokens", 0)) for r in rows)
    result.cached_tokens = sum(int(r.get("cached_input_tokens", 0)) for r in rows)
    result.output_tokens = sum(int(r.get("output_tokens", 0)) for r in rows)
    result.model_calls = len(rows)
    result.tool_calls = len(ctx.tool_events)
    result.tool_errors = sum(1 for e in ctx.tool_events if e.error)
    return result


def has_tools_form(reg: Registry, ident: str) -> bool:
    manifest = reg.get("agent", ident).manifest
    return isinstance(manifest, mf.AgentManifest) and manifest.with_tools is not None


def run_all(reg: Registry, only: str | None = None, *, live: bool = False, prompt: Path | None = None,
            tools: bool = False) -> list[Result]:
    """Every agent's cases. An agent with a `with_tools` form is run in both forms (scripted: the CI gate; live: only
    the form asked for, so one command never pays for both); `tools` = only that form."""
    ids = [only] if only else sorted(reg.ids("agent"))
    out: list[Result] = []
    for ident in ids:
        forms = [False, True] if has_tools_form(reg, ident) and not live else [False]
        if tools:
            forms = [True] if has_tools_form(reg, ident) else []
        out += [r for form in forms for r in run_agent(reg, ident, live=live, prompt=prompt, tools=form)]
    return out


# ── A/B: the same cases through two manifests ────────────────────────────────────────────────────────────────────────


def with_manifest(reg: Registry, ident: str, side: str) -> Registry:
    """`reg` with agent `ident` as `side` says: `current` (the tree) or a path to a manifest file (the old one, from
    git)."""
    if side == "current":
        return reg
    manifest = mf.load(Path(side))
    if not isinstance(manifest, mf.AgentManifest) or manifest.id != ident:
        raise ValueError(f"{side} is not the manifest of agent {ident}")
    comp = reg.get("agent", ident)
    clone = Registry(reg.root, reg.package)
    clone.components = {**reg.components, ("agent", ident): Component(manifest, comp.folder, comp.package, comp.group)}
    return clone


def run_ab(reg: Registry, ident: str, sides: tuple[str, str], *, live: bool = False) -> list[list[Result]]:
    """`base` = the single call, `tools` = the `with_tools` form, `current` = the manifest in the tree, or a manifest
    file."""
    forms = {"base", "tools"} == set(sides)  # the single call against its tools form: the same cases through both
    return [run_agent(reg if side in ("base", "tools") else with_manifest(reg, ident, side), ident, live=live,
                      tools=side == "tools", every=forms and live) for side in sides]


def summary(rows: list[Result]) -> dict[str, int]:
    return {"cases": len(rows), "passed": sum(r.passed for r in rows),
            "input": sum(r.input_tokens for r in rows), "cached": sum(r.cached_tokens for r in rows),
            "output": sum(r.output_tokens for r in rows), "model_calls": sum(r.model_calls for r in rows),
            "tool_calls": sum(r.tool_calls for r in rows), "tool_errors": sum(r.tool_errors for r in rows)}


def _line(label: str, s: dict[str, int]) -> str:
    return (f"{label:22s} {s['passed']}/{s['cases']}  tokens in {s['input']} (cached {s['cached']}) out {s['output']}"
            f"  model calls {s['model_calls']}  tool calls {s['tool_calls']}  tool errors {s['tool_errors']}")


def report(results: list[Result]) -> str:
    lines: list[str] = []
    by_agent: dict[str, list[Result]] = {}
    for r in results:
        by_agent.setdefault(r.agent, []).append(r)
    for ident, rows in by_agent.items():
        lines.append(_line(ident, summary(rows)))
        lines += [f"    FAIL {r.case}: {r.detail}" for r in rows if not r.passed]
    total = sum(r.passed for r in results)
    lines.append(f"{total}/{len(results)} cases pass")
    return "\n".join(lines)


def report_ab(ident: str, sides: tuple[str, str], runs: list[list[Result]]) -> str:
    a, b = (summary(r) for r in runs)
    lines = [_line(f"{ident} [{sides[0]}]", a), _line(f"{ident} [{sides[1]}]", b)]
    for key, label in (("input", "input tokens"), ("model_calls", "model calls"), ("tool_calls", "tool calls"),
                       ("tool_errors", "tool errors")):
        change = f"{(b[key] - a[key]) / a[key]:+.0%}" if a[key] else ("same" if b[key] == a[key] else "new")
        lines.append(f"    {label:14s} {a[key]} -> {b[key]} ({change})")
    lines.append(f"    cases passed   {a['passed']} of {a['cases']} -> {b['passed']} of {b['cases']}")
    for side, rows in zip(sides, runs, strict=True):
        lines += [f"    FAIL [{side}] {r.case}: {r.detail}" for r in rows if not r.passed]
    return "\n".join(lines)
