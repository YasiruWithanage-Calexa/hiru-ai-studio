"""What Phase 2 added to the core: reaching a sibling by id, the model-facing form of a tool, the fakes, `run`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from hiru_ai.cli import scaffold
from hiru_ai.cli.main import main
from hiru_ai.core import manifest as mf
from hiru_ai.core import parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import PortMissing, UnknownComponent
from hiru_ai.core.fakes import FakeScenes, ports_from
from hiru_ai.core.registry import Registry
from hiru_ai.tools.scene_read import tool as scene_read
from hiru_ai.tools.veo_fit import tool as veo_fit
from tests.hiru_ai.steps_fixtures import felt_scene, run_ctx

# ── parts: a sibling by id ─────────────────────────────────────────────────────────────────


def test_a_step_finds_a_sibling_by_id_and_gets_its_code():
    assert parts.step("refusal_screen").for_person("") == "that change could not be made as written"


def test_a_missing_or_disabled_sibling_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "hiru_ai"
    scaffold.create("step", "alpha", root)
    path = root / "steps" / "alpha" / "component.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("experimental", "disabled"), encoding="utf-8")
    monkeypatch.setattr(parts, "_registry", lambda: Registry(root).discover())
    with pytest.raises(UnknownComponent):
        parts.step("alpha", "step")
    with pytest.raises(UnknownComponent):
        parts.step("nobody")


# ── manifests and validate: uses, ports ────────────────────────────────────────────────────


def edit(root: Path, kind: str, ident: str, **subs: str) -> None:
    path = root / mf.LAYERS[kind] / ident / "component.yaml"
    text = path.read_text(encoding="utf-8")
    for old, new in subs.items():
        assert old in text, old
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def problems(root: Path) -> list[str]:
    return [str(p) for p in Registry(root).discover().validate()]


def test_a_step_that_uses_a_missing_or_disabled_step_is_a_problem(tmp_path: Path):
    root = tmp_path / "hiru_ai"
    scaffold.create("step", "alpha", root)
    scaffold.create("step", "beta", root)
    edit(root, "step", "alpha", **{"uses: []": "uses: [beta, ghost]"})
    edit(root, "step", "beta", **{"status: experimental": "status: disabled"})
    found = problems(root)
    assert any("step 'ghost'" in p and "does not exist" in p for p in found)
    assert any("step 'beta'" in p and "disabled" in p for p in found)


def test_steps_that_use_each_other_in_a_circle_are_found(tmp_path: Path):
    root = tmp_path / "hiru_ai"
    scaffold.create("step", "alpha", root)
    scaffold.create("step", "beta", root)
    edit(root, "step", "alpha", **{"uses: []": "uses: [beta]"})
    edit(root, "step", "beta", **{"uses: []": "uses: [alpha]"})
    assert any("reference cycle" in p for p in problems(root))


def test_removing_a_step_lists_who_uses_it(tmp_path: Path):
    root = tmp_path / "hiru_ai"
    scaffold.create("step", "alpha", root)
    scaffold.create("tool", "gamma", root)
    edit(root, "tool", "gamma", **{"uses: []": "uses: [alpha]"})
    assert Registry(root).discover().refs_to("step", "alpha") == [("tool", "gamma")]


def test_a_tool_may_only_name_ports_a_run_has(tmp_path: Path):
    root = tmp_path / "hiru_ai"
    scaffold.create("tool", "gamma", root)
    edit(root, "tool", "gamma", **{"ports: []": "ports: [scenes, warehouse]"})
    assert any("warehouse" in p and "not run ports" in p for p in problems(root))


# ── tools in a graph: the form a model sees ────────────────────────────────────────────────


def call(tool: Any, args: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    graph = StateGraph(MessagesState, context_schema=RunContext)
    graph.add_node("tools", ToolNode([tool]))
    graph.add_edge(START, "tools")
    message = AIMessage(content="", tool_calls=[{"name": tool.name, "args": args, "id": "1"}])
    out = graph.compile().invoke({"messages": [message]}, context=ctx)
    return json.loads(out["messages"][-1].content)  # type: ignore[no-any-return]


def test_a_tool_runs_inside_a_graph_with_the_runs_context_injected():
    out = call(veo_fit.as_tool(), {"words": 8}, RunContext())
    assert out["duration_s"] == 4 and out["fits"] is True


def test_the_model_cannot_choose_the_production():
    scene, lines, shots = felt_scene()
    ctx = run_ctx(scene, lines, shots)
    out = call(scene_read.as_tool(), {"scene": scene["id"], "production_id": str(uuid4())}, ctx)
    assert out["heading"] == scene["heading"]  # the extra argument is ignored; the run's production was used


def test_a_refusal_is_the_tools_answer_not_a_crash():
    scene, lines, shots = felt_scene()
    out = call(scene_read.as_tool(), {"scene": "E9S9"}, run_ctx(scene, lines, shots))
    assert "no scene" in out["error"] and out["how_to_fix"] and out["example"]


# ── the run and the fakes ──────────────────────────────────────────────────────────────────


def test_a_missing_port_names_itself():
    with pytest.raises(PortMissing, match="'images' port"):
        RunContext().need("images", "ImageGen")


def test_the_scene_fake_saves_a_plan_the_way_the_table_would():
    scene, lines, shots = felt_scene()
    fake = FakeScenes(scenes=[scene], lines=lines, shots=shots)
    fake.save_plan(scene["id"], [{**shots[0], "framing": "CU"}, {"id": "new", "scene_id": scene["id"], "number": 3}],
                   [shots[1]["id"]], [], {"status": "split"})
    ids = [s["id"] for s in fake.shots(scene["id"])]
    assert shots[0]["id"] in ids and shots[1]["id"] not in ids and "new" in ids
    assert next(s for s in fake.shot_rows if s["id"] == shots[0]["id"])["framing"] == "CU"
    assert fake.scene_rows[0]["status"] == "split"


def test_the_fakes_scope_scenes_to_the_production():
    scene, _, _ = felt_scene()
    fake: Any = ports_from({"scenes": [scene]}).scenes
    assert fake.scenes(uuid4(), None) == [] and len(fake.scenes(scene["production_id"], None)) == 1


# ── hiru-ai run ────────────────────────────────────────────────────────────────────────────


def case(tmp_path: Path, body: Any) -> str:
    path = tmp_path / "case.json"
    path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return str(path)


def test_run_prints_the_parts_answer_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["run", "tool", "veo_fit", "--input", case(tmp_path, {"args": {"words": 20}})]) == 0
    assert json.loads(capsys.readouterr().out)["duration_s"] == 8


def test_run_reports_a_case_that_is_not_json_or_not_an_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["run", "step", "refusal_screen", "--input", case(tmp_path, "{nope")]) == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert main(["run", "step", "refusal_screen", "--input", case(tmp_path, [1])]) == 2


def test_run_reports_a_part_that_is_not_there(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["run", "tool", "teleporter", "--input", case(tmp_path, {})]) == 2
    assert "teleporter" in capsys.readouterr().err


def test_run_will_not_write_to_a_live_database_unasked(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    body = {"args": {"scene_id": "x"}}
    assert main(["run", "tool", "scene_write", "--live", "--input", case(tmp_path, body)]) == 2
    assert "--allow-writes" in capsys.readouterr().err


def test_a_tools_refusal_is_printed_as_the_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    body = {"production_id": str(uuid4()), "args": {"scene": "00000000-0000-4000-8000-000000000000"}}
    assert main(["run", "tool", "scene_read", "--input", case(tmp_path, body)]) == 2
    assert "no scene 00000000-0000-4000-8000-000000000000 in this production" in capsys.readouterr().err
