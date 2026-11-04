"""The tool contract and its runtime (plan/2026-11-04, Phase 0): manifests, validation, the result budget, errors that
teach, the react middleware, usage columns, scripted evals and the scaffold."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import yaml
from langchain_core.messages import AIMessage, ToolMessage

from hiru_ai.cli import evals, scaffold
from hiru_ai.cli.main import main
from hiru_ai.core import manifest as mf
from hiru_ai.core import tooling
from hiru_ai.core.agents import Agent
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import HiruAIError, ManifestError, ToolRefused
from hiru_ai.core.fakes import ports_from
from hiru_ai.core.registry import PACKAGE_ROOT, Registry, default
from hiru_ai.core.usage import Detail, UsageCallback

_EXAMPLE = json.loads((Path(__file__).parents[2] / "src/libs/hiru_ai/tools/timing_check/examples/basic.json")
                      .read_text("utf-8"))
PRODUCTION, SCENE = _EXAMPLE["production_id"], _EXAMPLE["scene_id"]  # the Kasun / Anudi phone scene, E1S2


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "hiru_ai"


def problems(root: Path) -> list[str]:
    return [str(p) for p in Registry(root).discover().validate() if p.level == "error"]


def edit(root: Path, kind: str, ident: str, **replace: str) -> None:
    path = root / mf.LAYERS[kind] / ident / "component.yaml"
    text = path.read_text(encoding="utf-8")
    for old, new in replace.items():
        assert old in text, f"{old!r} not in the manifest"
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


# ── the manifest ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_writes_is_a_one_release_alias_of_effect():
    base = {"id": "xy", "kind": "tool", "summary": "does a thing"}
    old = mf.parse({**base, "writes": True})
    assert isinstance(old, mf.ToolManifest) and old.effect == "write" and old.writes
    assert mf.parse({**base, "writes": False}).effect == "read"  # type: ignore[union-attr]
    assert mf.parse(base).effect == "read"  # type: ignore[union-attr]
    with pytest.raises(ManifestError, match="not `effect` and `writes`"):
        mf.parse({**base, "writes": True, "effect": "stage"})
    with pytest.raises(ManifestError, match="effect"):
        mf.parse({**base, "effect": "delete"})


def test_every_tool_in_the_package_has_an_effect_a_guide_and_an_example():
    reg = default()
    for ident in reg.ids("tool"):
        m = reg.get("tool", ident).manifest
        assert isinstance(m, mf.ToolManifest)
        assert m.effect in ("read", "stage", "write") and m.guide.strip(), ident
        assert all((reg.get("tool", ident).folder / rel).is_file() for rel in m.examples), ident


# ── validate ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_scaffolded_tool_passes_validate_for_each_effect(root: Path):
    scaffold.create("tool", "plain_read", root)
    scaffold.create("tool", "card_maker", root, effect="stage")
    assert problems(root) == []
    assert "staging" in (yaml.safe_load((root / "tools/card_maker/component.yaml").read_text("utf-8"))["ports"])


def test_a_tool_needs_a_guide_that_says_when_not_to_use_it(root: Path):
    scaffold.create("tool", "plain_read", root)
    edit(root, "tool", "plain_read", **{"  Do not use it for TODO (use another_tool instead).": "  Use it often."})
    assert any("does not say when NOT to use" in p for p in problems(root))
    path = root / "tools/plain_read/component.yaml"
    path.write_text(path.read_text("utf-8").split("guide:")[0], encoding="utf-8")
    assert any("has no `guide`" in p for p in problems(root))


def test_a_tool_may_not_take_the_id_of_another_kind(root: Path):
    scaffold.create("step", "dup_step", root)
    scaffold.create("tool", "dup_tool", root)
    shutil.move(str(root / "tools/dup_tool"), str(root / "tools/dup_step"))
    edit(root, "tool", "dup_step", **{"id: dup_tool": "id: dup_step"})
    assert any("ids are unique across kinds" in p for p in problems(root))
    scaffold.create("step", "other_step", root)
    with pytest.raises(HiruAIError, match="already a step"):
        scaffold.create("tool", "other_step", root)


def test_a_stage_tool_must_reach_the_staging_port(root: Path):
    scaffold.create("tool", "card_maker", root, effect="stage")
    edit(root, "tool", "card_maker", **{"ports: [staging]": "ports: []"})
    assert any("staging" in p for p in problems(root))


def test_scaffold_refuses_a_wrapped_step_that_does_not_exist_or_shares_its_id(root: Path):
    with pytest.raises(HiruAIError, match="not a step"):
        scaffold.create("tool", "wrapper", root, wraps="nothing")
    scaffold.create("step", "inner", root)
    with pytest.raises(HiruAIError, match="never takes the id"):
        scaffold.create("tool", "inner", root, wraps="inner")
    scaffold.create("tool", "wrapper", root, wraps="inner")
    assert problems(root) == []


def agent_with(root: Path, tools: list[str], **extra: str) -> None:
    scaffold.create("agent", "asker", root)
    edit(root, "agent", "asker", **{"shape: structured": "shape: react", "tools: []": f"tools: [{', '.join(tools)}]",
                                    **extra})


def test_an_agent_may_not_list_a_tool_that_writes(root: Path):
    for ident, effect in (("reader", "read"), ("saver", "write")):
        scaffold.create("tool", ident, root, effect=effect)
    agent_with(root, ["reader", "saver"])
    found = problems(root)
    assert any("saver" in p and "writes stored data" in p for p in found)
    assert not any("reader" in p for p in found)


def test_an_agent_sees_at_most_eight_tools_and_none_twice(root: Path):
    ids = [f"tool_{n}" for n in range(9)]
    for ident in ids:
        scaffold.create("tool", ident, root)
    agent_with(root, ids)
    assert any("at most 8" in p for p in problems(root))
    shutil.rmtree(root / "agents")
    agent_with(root, [*ids[:2], ids[0]])
    assert any("twice" in p for p in problems(root))


def test_gate_names_only_stage_tools_the_agent_has(root: Path):
    scaffold.create("tool", "reader", root)
    scaffold.create("tool", "card_maker", root, effect="stage")
    agent_with(root, ["reader", "card_maker"], **{"writes_dialogue: false": "writes_dialogue: false\ngate: [reader]"})
    assert any("whose effect is read" in p for p in problems(root))
    edit(root, "agent", "asker", **{"gate: [reader]": "gate: [card_maker, missing]"})
    assert any("not one of its tools" in p for p in problems(root))
    edit(root, "agent", "asker", **{"gate: [card_maker, missing]": "gate: [card_maker]"})
    assert problems(root) == []


# ── the tool runtime ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_result_over_budget_loses_the_tail_of_its_biggest_list_and_says_how_to_narrow():
    data = {"total": 200, "items": [{"n": n, "text": "word " * 20} for n in range(200)], "small": [1, 2]}
    cut, was_cut = tooling.fit(data, 500, "Ask for less: `page_size`.")
    assert was_cut and tooling.tokens_of(tooling.dumps(cut)) <= 500
    assert cut["total"] == 200 and cut["small"] == [1, 2], "only the big list is cut"
    assert 0 < len(cut["items"]) < 200 and cut["items"][0]["n"] == 0
    assert cut["truncated"]["hint"] == "Ask for less: `page_size`."
    shown, of = cut["truncated"]["shown"]["items"].split(" of ")
    assert int(shown) == len(cut["items"]) and int(of) == 200


def test_a_result_inside_the_budget_is_untouched_and_a_long_text_is_shortened_when_no_list_can_be():
    small = {"a": [1, 2, 3]}
    assert tooling.fit(small, 500, "h") == (small, False)
    cut, was_cut = tooling.fit({"text": "x" * 20000}, 300, "h")
    assert was_cut and len(cut["text"]) < 3000 and cut["text"].endswith("…")


def test_sinhala_is_counted_dearer_than_latin_and_goes_out_byte_for_byte():
    line = "මම ගෙදර යනවා"
    assert tooling.tokens_of(line * 10) > tooling.tokens_of("abc def ghi " * 10)
    assert line in tooling.dumps({"text": line}), "never \\u escapes"


def test_closest_names_forgive_a_nickname_a_typo_and_a_code():
    names = ["Kasun", "Anudi", "Anudi's Father", "Kasun's Food Three-Wheeler"]
    assert tooling.closest("father", names)[0] == "Anudi's Father"
    assert tooling.closest("Kasunn", names)[0] == "Kasun"
    refused = tooling.not_found("character", "Anudy", names, example='{"name_or_code": "C02"}')
    assert "Anudi" in refused.how_to_fix and refused.example


def test_paging_says_the_next_page_and_the_total():
    items = list(range(25))
    first, meta = tooling.page(items, 1, 10)
    assert first == list(range(10)) and meta == {"total": 25, "page": 1, "page_size": 10, "next_page": 2}
    last, meta = tooling.page(items, 3, 10)
    assert last == [20, 21, 22, 23, 24] and meta["next_page"] is None
    assert tooling.page(items, 1, 500)[1]["page_size"] == tooling.PAGE_SIZE_MAX


def test_shots_are_named_the_way_a_person_names_them():
    assert [tooling.shot_number(v) for v in ("S03", "s3", "3", 3, " S 03 ")] == [3] * 5
    assert tooling.shot_code(4) == "S04"
    with pytest.raises(ToolRefused) as refused:
        tooling.shot_number("the third")
    assert refused.value.how_to_fix and refused.value.example


def scene_ctx(**kw: Any) -> RunContext:
    return RunContext(production_id=UUID(PRODUCTION), ports=ports_from(_EXAMPLE["fixtures"]), **kw)


def test_a_scene_is_named_by_episode_and_number_or_defaults_to_the_run_scene():
    ctx = scene_ctx(scene_id=UUID(SCENE))
    assert tooling.scene_in_scope(ctx, None)[1]["id"] == SCENE
    assert tooling.scene_in_scope(ctx, "E1S2")[1]["id"] == SCENE
    assert tooling.scene_in_scope(ctx, "2")[1]["id"] == SCENE
    assert tooling.scene_in_scope(ctx, SCENE)[1]["id"] == SCENE
    assert tooling.scene_label(tooling.scene_in_scope(ctx, "2")[1]) == "E1S2"
    with pytest.raises(ToolRefused) as missing:
        tooling.scene_in_scope(ctx, "E1S9")
    assert "E1S2" in missing.value.how_to_fix
    with pytest.raises(ToolRefused, match="no scene in scope"):
        tooling.scene_in_scope(scene_ctx(), None)
    with pytest.raises(ToolRefused, match="not a scene"):
        tooling.scene_in_scope(ctx, "the kitchen")


def test_the_description_a_model_reads_is_the_summary_then_the_guide():
    reg = default()
    manifest = reg.get("tool", "veo_fit").manifest
    lc = reg.module("tool", "veo_fit", "tool").as_tool()
    assert lc.description.startswith(manifest.summary) and manifest.guide.strip() in lc.description  # type: ignore[union-attr]


def call(tool: Any, ctx: RunContext, **kwargs: Any) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(tool.func(SimpleNamespace(context=ctx), **kwargs))
    return out


def test_a_refused_call_answers_with_how_to_fix_and_example_and_is_logged():
    reg = default()
    tool = reg.module("tool", "dialogue_read", "tool").as_tool()
    ctx = scene_ctx()
    answer = call(tool, ctx, scene_id="not-in-this-production")
    assert answer["error"].endswith("is not a scene")
    assert [(e.tool, e.error) for e in ctx.tool_events] == [("dialogue_read", "refused")]
    ok = call(tool, ctx, scene_id=SCENE)
    assert ok["lines"][0]["speaker"] == "Kasun"
    assert ctx.tool_events[-1].error == "" and ctx.tool_events[-1].result_tokens > 0


def test_a_missing_port_is_a_clear_error_never_a_crashed_turn():
    tool = default().module("tool", "dialogue_read", "tool").as_tool()
    ctx = RunContext(production_id=UUID(PRODUCTION))  # no scene store at all
    answer = call(tool, ctx, scene_id=SCENE)
    assert answer["error"] == "That lookup is not available right now." and answer["how_to_fix"]
    assert ctx.tool_events[0].error == "PortMissing"


# ── every tool, on its own example ───────────────────────────────────────────────────────────────────────────────────

READ_AND_STAGE = [i for i in default().ids("tool")
                  if default().get("tool", i).manifest.effect != "write"]  # type: ignore[union-attr]


@pytest.mark.parametrize("ident", READ_AND_STAGE)
def test_a_tools_concise_answer_to_its_example_is_inside_its_budget(ident: str):
    from hiru_ai.core.testing import example_ctx, example_of

    case = example_of(ident)
    module = default().module("tool", ident, "tool")
    lc = module.as_tool()
    ctx = example_ctx(case)
    args = {k: v for k, v in case["args"].items() if v is not None}
    text = lc.func(SimpleNamespace(context=ctx), **args)
    budget = default().get("tool", ident).manifest.max_result_tokens  # type: ignore[union-attr]
    assert tooling.tokens_of(text) <= budget, f"{ident}: {tooling.tokens_of(text)} tokens for a budget of {budget}"
    assert "truncated" not in json.loads(text), f"{ident}: its own example is cut"
    assert ctx.tool_events and ctx.tool_events[0].error == "", f"{ident}: {text[:200]}"


def test_no_agent_lists_a_write_tool_today_and_none_lists_more_than_eight():
    reg = default()
    for ident in reg.ids("agent"):
        manifest = reg.get("agent", ident).manifest
        assert len(manifest.tools) <= mf.MAX_TOOLS  # type: ignore[union-attr]
        assert not [t for t in manifest.tools  # type: ignore[union-attr]
                    if reg.get("tool", t).manifest.effect == "write"], ident  # type: ignore[union-attr]


# ── the react middleware ──────────────────────────────────────────────────────────────────────────────────────────────


def test_limits_clear_old_results_and_tool_retry_are_built_from_the_manifest():
    from hiru_ai.core.middleware import react

    built = react.build(["limits", "clear_old_results", "tool_retry"], tier="high", read_tools=["scene_read"],
                        max_tool_calls=5, max_model_calls=3)
    assert [type(m).__name__ for m in built] == ["ToolCallLimitMiddleware", "ModelCallLimitMiddleware",
                                                 "ContextEditingMiddleware", "ToolRetryMiddleware"]
    assert react.build(["tool_retry"], tier="high", read_tools=[]) == [], "nothing to retry"


def test_the_react_middleware_names_are_refused_on_a_structured_agent(root: Path):
    scaffold.create("agent", "asker", root)
    edit(root, "agent", "asker", **{"middleware: [": "middleware: [limits, "})
    assert any("apply to react agents" in p for p in problems(root))


# ── usage rows ────────────────────────────────────────────────────────────────────────────────────────────────────────


def usage_run(detail: Detail | None) -> list[dict[str, Any]]:
    from langchain_core.outputs import ChatGeneration, LLMResult

    rows: list[dict[str, Any]] = []
    cb = UsageCallback(rows.append, "agent.x", detail=detail)
    run_id = UUID(int=7)
    sent = [[ToolMessage(content="x" * 400, tool_call_id="1"), ToolMessage(content="y" * 400, tool_call_id="2")]]
    cb.on_chat_model_start({}, sent, run_id=run_id)
    answer = AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "1", "type": "tool_call"},
                                               {"name": "b", "args": {}, "id": "2", "type": "tool_call"}],
                       usage_metadata={"input_tokens": 900, "output_tokens": 30, "total_tokens": 930,
                                       "input_token_details": {"cache_read": 700}},
                       response_metadata={"model_name": "gpt-5"})
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=answer)]]), run_id=run_id)
    return rows


def test_a_usage_row_names_the_component_and_its_tool_loop_only_when_asked():
    plain = usage_run(None)
    assert set(plain[0]) == {"phase", "model", "input_tokens", "cached_input_tokens", "output_tokens"}
    (row,) = usage_run(Detail("agent:chat_answerer", 2, "abc123"))
    assert row["component"] == "agent:chat_answerer" and row["component_version"] == 2
    assert row["prompt_hash"] == "abc123" and row["tool_calls"] == 2 and row["tool_result_tokens"] == 200
    assert row["input_tokens"] == 900 and row["cached_input_tokens"] == 700


# ── scripted evals and the A/B ────────────────────────────────────────────────────────────────────────────────────────


def probe_agent(root: Path, cases: list[dict[str, Any]], tools: str = "[dialogue_read]") -> Registry:
    """A react agent in a temporary registry, listing a REAL tool: the loop is exercised without a model."""
    shutil.copytree(PACKAGE_ROOT / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__", "tests"))
    scaffold.create("agent", "probe", root)
    edit(root, "agent", "probe", **{"shape: structured": "shape: react", "tools: []": f"tools: {tools}"})
    (root / "agents/probe/evals/cases.yaml").write_text(yaml.safe_dump(cases), encoding="utf-8")
    return Registry(root).discover()


ASK = {"input": {"text": "what does Kasun say?"}, "production_id": PRODUCTION, "scene_id": SCENE,
       "reply": {"answer": "Started with Rs. 5,000."}, "expect": {"answer": "Started with Rs. 5,000."}}


@pytest.fixture
def fixtures() -> dict[str, Any]:
    return _EXAMPLE["fixtures"]


def test_a_scripted_case_plays_the_tool_calls_and_counts_them(root: Path, fixtures: dict[str, Any]):
    case = {**ASK, "name": "asks", "fixtures": fixtures,
            "tool_calls": [{"name": "dialogue_read", "args": {"scene_id": SCENE},
                            "expect": {"lines": [{"speaker": "Kasun"}]}}]}
    reg = probe_agent(root, [case])
    (result,) = evals.run_agent(reg, "probe")
    assert result.passed, result.detail
    assert (result.tool_calls, result.tool_errors, result.model_calls) == (1, 0, 2)


def test_a_case_that_needs_no_tool_fails_when_the_agent_calls_one(root: Path, fixtures: dict[str, Any]):
    case = {**ASK, "name": "no tool please", "fixtures": fixtures, "expect_no_tools": True,
            "tool_calls": [{"name": "dialogue_read", "args": {"scene_id": SCENE}}]}
    (result,) = evals.run_agent(probe_agent(root, [case]), "probe")
    assert not result.passed and "needs no tool" in result.detail


def test_a_tool_error_in_a_case_fails_it_unless_the_case_expects_one(root: Path, fixtures: dict[str, Any]):
    case = {**ASK, "name": "bad scene", "fixtures": fixtures,
            "tool_calls": [{"name": "dialogue_read", "args": {"scene_id": "zzz"}}]}
    (result,) = evals.run_agent(probe_agent(root, [case]), "probe")
    assert not result.passed and result.tool_errors == 1
    (allowed,) = evals.run_agent(probe_agent(root / "again", [{**case, "allow_tool_errors": True}]), "probe")
    assert allowed.passed


def test_ab_runs_the_same_cases_through_two_manifests(root: Path, fixtures: dict[str, Any], tmp_path: Path):
    case = {**ASK, "name": "asks", "fixtures": fixtures,
            "tool_calls": [{"name": "dialogue_read", "args": {"scene_id": SCENE}}]}
    reg = probe_agent(root, [case])
    old = tmp_path / "old.yaml"
    shutil.copy(root / "agents/probe/component.yaml", old)
    edit(root, "agent", "probe", **{"tools: [dialogue_read]": "tools: [dialogue_read, veo_fit]"})
    reg = Registry(root).discover()
    a, b = evals.run_ab(reg, "probe", (str(old), "current"))
    assert a[0].passed and b[0].passed
    text = evals.report_ab("probe", (str(old), "current"), [a, b])
    assert "tool calls" in text and "model calls" in text and "[current]" in text
    assert [t.name for t in Agent(evals.with_manifest(reg, "probe", str(old)), "probe").tools()] == ["dialogue_read"]
    assert [t.name for t in Agent(reg, "probe").tools()] == ["dialogue_read", "veo_fit"], "sorted by id"


def test_the_tool_block_is_sorted_and_stable_and_drift_is_caught(root: Path, fixtures: dict[str, Any]):
    from hiru_ai.core.errors import StaticPrefixError
    from hiru_ai.core.middleware.base import ModelCall
    from hiru_ai.core.middleware.static_first import StaticFirst

    reg = probe_agent(root, [], tools="[veo_fit, dialogue_read]")
    agent = Agent(reg, "probe")
    block = agent.tool_block()
    assert [t["name"] for t in json.loads(block)] == ["dialogue_read", "veo_fit"]
    assert agent.tool_block() == block, "built once"
    mw, ctx = StaticFirst(), RunContext(strict=True)
    call_ = ModelCall(component="agent:probe", phase="p", tier="high", system="s", user="u", tools=block)
    assert mw(call_, ctx, lambda c: "ok") == "ok" and mw(call_, ctx, lambda c: "ok") == "ok"
    drifted = [{**t, "description": t["description"] + " (reworded)"} for t in json.loads(block)]
    with pytest.raises(StaticPrefixError, match="changed between calls"):
        mw(ModelCall(component="agent:probe", phase="p", tier="high", system="s", user="u",
                     tools=json.dumps(drifted, sort_keys=True)), ctx, lambda c: "ok")
    unsorted = json.dumps(list(reversed(json.loads(block))))
    with pytest.raises(StaticPrefixError, match="not sorted"):
        mw(ModelCall(component="agent:other", phase="p", tier="high", system="s", user="u", tools=unsorted), ctx,
           lambda c: "ok")


# ── the command line ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_new_tool_writes_the_contract_filled_in(root: Path, capsys: pytest.CaptureFixture[str]):
    scaffold.create("step", "inner", root)
    assert main(["--root", str(root), "new", "tool", "wrapper", "--effect", "read", "--wraps", "inner"]) == 0
    manifest = yaml.safe_load((root / "tools/wrapper/component.yaml").read_text("utf-8"))
    assert manifest["uses"] == ["inner"] and manifest["effect"] == "read" and "Do not use" in manifest["guide"]
    assert main(["--root", str(root), "validate", "--no-import"]) == 0
    assert main(["--root", str(root), "new", "tool", "inner", "--wraps", "inner"]) == 2


def test_run_tool_takes_a_format_and_says_what_the_model_would_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"args": {"words": 19}}), encoding="utf-8")
    assert main(["run", "tool", "veo_fit", "--input", str(case), "--format", "detailed"]) == 0
    captured = capsys.readouterr()
    assert "tokens (budget" in captured.err and isinstance(json.loads(captured.out), dict)


def test_a_refused_tool_run_exits_2_with_the_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"production_id": PRODUCTION, "args": {"scene_id": "nope"}}), encoding="utf-8")
    assert main(["run", "tool", "dialogue_read", "--input", str(case)]) == 2
    assert "is not a scene" in capsys.readouterr().err
