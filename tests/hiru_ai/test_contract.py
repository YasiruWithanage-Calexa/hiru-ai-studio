"""Generated contract tests: one set of checks, run over every part in the registry (plan §5.8).

Nothing is listed here by hand. A new part is picked up the moment its folder exists, and a part that breaks the
contract fails these tests under its own name. The checks that need an agent builder (answering a fake model with a
valid Output, a graph compiling and drawing) arrive with the builders: Phase 4 agents, Phase 5 panels, Phase 6 systems.
"""
from __future__ import annotations

import copy
import json
from dataclasses import fields, replace
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from hiru_ai.cli.main import main
from hiru_ai.core import manifest as mf
from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import ports_from
from hiru_ai.core.prompts import Prompt
from hiru_ai.core.registry import Component, default

REGISTRY = default()
PARTS = [pytest.param(c, id=f"{k}/{i}") for (k, i), c in sorted(REGISTRY.components.items())]
AGENTS = [p for p in PARTS if p.values[0].manifest.kind == "agent"]


def test_no_manifest_is_unreadable():
    assert [str(p) for p in REGISTRY.errors] == []


@pytest.mark.parametrize("comp", PARTS)
def test_the_part_validates_on_its_own(comp: Component):
    mine = f"{comp.manifest.kind} {comp.manifest.id}"
    assert [str(p) for p in REGISTRY.validate() if p.where == mine and p.level == "error"] == []


@pytest.mark.parametrize("comp", PARTS)
def test_the_part_lives_where_its_kind_says(comp: Component):
    layer = comp.folder.parent.parent if comp.group else comp.folder.parent  # a group's parts sit one folder deeper
    assert layer.name == mf.LAYERS[comp.manifest.kind] and comp.folder.name == comp.manifest.id
    assert (comp.folder.parent.name == comp.group) if comp.group else True


@pytest.mark.parametrize("comp", AGENTS)
def test_the_agents_prompts_are_static_files_with_a_hash(comp: Component):
    for rel in comp.manifest.prompts.values():  # type: ignore[union-attr]
        prompt = Prompt.load(comp.folder / rel)
        assert prompt.sha and prompt.text.strip()


# ── steps and tools (Phase 2) ──────────────────────────────────────────────────────────────

STEPS = [p for p in PARTS if p.values[0].manifest.kind == "step"]
TOOLS = [p for p in PARTS if p.values[0].manifest.kind == "tool"]
RUNNABLE = STEPS + TOOLS


def example(comp: Component) -> dict[str, Any]:
    return json.loads((comp.folder / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_layers_have_the_parts_the_plan_lists():
    """Every part the plan names exists. Later phases add more, so this is a floor."""
    assert set(REGISTRY.ids("step")) >= {
        "scene_kernel", "kernel_score", "board_settle", "ripple", "refusal_screen", "verbatim_check", "feeling",
        "serialize", "chunk", "extract_text", "canon_rules", "bridges", "stage_check", "scene_listing", "note_merge",
        "shot_joins", "prompt_lint"}
    assert set(REGISTRY.ids("tool")) >= {
        "scene_read", "scene_write", "dialogue_read", "shot_write", "canon_write", "structure_write", "timing_check",
        "veo_fit", "technique_lookup", "image_generate", "search_kb",
        # plan/2026-11-04 Phase 1
        "canon_read", "canon_find", "memory_search", "questions_read", "shot_read", "scene_reading_read",
        "episode_read",
        "frame_read", "glossary_read", "plan_try", "plan_score", "staging_check", "dialogue_check", "continuity_check",
        "prompt_check", "change_propose", "memory_propose"}


@pytest.mark.parametrize("comp", RUNNABLE)
def test_the_part_has_an_example_and_runs_alone_from_the_command_line(comp: Component,
                                                                        capsys: pytest.CaptureFixture[str]):
    path = comp.folder / "examples" / "basic.json"
    assert path.is_file(), f"{comp.manifest.id} needs examples/basic.json for `hiru-ai run`"
    assert main(["run", comp.manifest.kind, comp.manifest.id, "--input", str(path)]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), dict)


@pytest.mark.parametrize("comp", STEPS)
def test_a_step_takes_json_and_gives_json_and_never_mutates_its_input(comp: Component):
    run = REGISTRY.resolve("step", comp.manifest.id, comp.manifest.entry)  # type: ignore[union-attr]
    case = example(comp)
    before = json.dumps(case, sort_keys=True)
    json.dumps(run(case))
    assert json.dumps(case, sort_keys=True) == before


@pytest.mark.parametrize("comp", TOOLS)
def test_a_tool_has_typed_arguments_and_result_and_a_langchain_form_the_model_cannot_scope(comp: Component):
    mod = REGISTRY.module("tool", comp.manifest.id, "tool")
    assert issubclass(mod.Args, BaseModel) and issubclass(mod.Result, BaseModel) and callable(mod.run)
    lc = mod.as_tool()
    assert lc.name == comp.manifest.id
    assert lc.description == tooling.description(comp.manifest.summary, comp.manifest.guide)  # type: ignore[union-attr]
    assert set(lc.args) == set(mod.Args.model_fields)
    json.dumps(mod.Args.model_json_schema())
    forbidden = {"production_id", "actor_user_id", "job_id", "ports", "ctx", "runtime", "corpora", "document_ids"}
    assert not forbidden & set(mod.Args.model_fields), "scope comes from the run, never from a model's arguments"


@pytest.mark.parametrize("comp", TOOLS)
def test_a_tool_uses_only_the_ports_it_declares_and_its_effect_says_what_it_may_change(comp: Component):
    case = example(comp)
    mod = REGISTRY.module("tool", comp.manifest.id, "tool")
    ports = ports_from(case.get("fixtures") or {})
    declared = set(comp.manifest.ports)  # type: ignore[union-attr]
    narrowed = replace(ports, **{f.name: None for f in fields(ports) if f.name not in declared})
    production, scene = case.get("production_id"), case.get("scene_id")
    ctx = RunContext(production_id=UUID(production) if production else None, ports=narrowed,
                     corpora=tuple(case.get("corpora") or ()), scene_id=UUID(scene) if scene else None,
                     said=str(case.get("said") or ""))
    watched = [getattr(narrowed, n) for n in declared]
    def stored(port: Any) -> dict[str, Any]:  # the rows a port holds; `asked` / `calls` only log how it was used
        return {k: copy.deepcopy(v) for k, v in vars(port).items() if k not in ("asked", "calls")}

    before = [stored(p) for p in watched]
    mod.run(mod.Args.model_validate(case["args"]), ctx)  # a PortMissing here means an undeclared port was used
    changed = [stored(p) != b for p, b in zip(watched, before, strict=True)]
    effect = comp.manifest.effect  # type: ignore[union-attr]
    # read changes nothing anywhere; stage leaves a card in the staging port and nothing else; write changes the stores
    assert any(changed) == (effect != "read"), (
        f"{comp.manifest.id}: effect={effect} but its example "
        f"{'changed' if any(changed) else 'changed nothing in'} the stores")
    if effect == "stage":
        assert [n for n, c in zip(declared, changed, strict=True) if c] == ["staging"], \
            "a stage tool leaves only a card"


@pytest.mark.parametrize("comp", RUNNABLE)
def test_what_a_part_uses_exists_and_is_a_step(comp: Component):
    for kind, ident in comp.manifest.refs():
        assert (kind, ident) in REGISTRY.components
        assert kind == "step" or (comp.manifest.kind == "step" and kind == "tool"), \
            "a tool reaches steps; a step may reach tools"
