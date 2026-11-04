"""Generated contract tests for every panel (plan/2026-11-03 §5.8, Phase 5): it compiles, it draws, its wiring is
snapshot-tested, and taking any one member out of the manifest still compiles. Nothing is listed by hand: a new panel
folder is picked up the moment it exists."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hiru_ai.core import manifest as mf
from hiru_ai.core.patterns import PATTERNS, mermaid
from hiru_ai.core.registry import Component, default

REGISTRY = default()
PANELS = [pytest.param(c, id=c.manifest.id) for (k, _), c in sorted(REGISTRY.components.items()) if k == "panel"]
UPDATE = os.environ.get("HIRU_AI_UPDATE") == "1"


def graph_module(comp: Component):  # type: ignore[no-untyped-def]
    return REGISTRY.module("panel", comp.manifest.id, "graph")


def test_the_plan_lists_these_panels():
    ungrouped = {i for i in REGISTRY.ids("panel") if not REGISTRY.get("panel", i).group}  # a group's are its own
    assert ungrouped == {"director_board", "plan_review", "shot_review", "structure_draft"}


def test_the_manifests_pattern_names_are_the_library():
    assert set(PATTERNS) == {"sequential", "fanout", "board", "critics_judge", "generate_critique", "router",
                             "human_gate"}


@pytest.mark.parametrize("comp", PANELS)
def test_the_panel_uses_a_pattern_of_the_library_and_names_what_it_needs(comp: Component):
    m = comp.manifest
    assert isinstance(m, mf.PanelManifest) and m.pattern in PATTERNS
    for role in mf.PATTERN_ROLES.get(m.pattern, {}):
        assert getattr(m, role), f"{m.id}: pattern {m.pattern} needs {role}"


@pytest.mark.parametrize("comp", PANELS)
def test_the_panel_compiles_and_draws_itself(comp: Component):
    drawn = mermaid(graph_module(comp).blank(REGISTRY))
    assert drawn.startswith("---") and "__start__" in drawn and "__end__" in drawn


@pytest.mark.parametrize("comp", PANELS)
def test_the_wiring_matches_the_snapshot(comp: Component):
    snapshot = comp.folder / "tests" / "graph.mmd"
    drawn = mermaid(graph_module(comp).blank(REGISTRY))
    if UPDATE:
        snapshot.write_text(drawn, encoding="utf-8")
    assert snapshot.is_file(), "write the snapshot with HIRU_AI_UPDATE=1 pytest tests/hiru_ai/test_panels_contract.py"
    assert snapshot.read_text(encoding="utf-8") == drawn, "the wiring changed; if on purpose: HIRU_AI_UPDATE=1"


@pytest.mark.parametrize("comp", PANELS)
def test_taking_any_member_out_of_the_manifest_still_compiles(comp: Component):
    m = comp.manifest
    assert isinstance(m, mf.PanelManifest)
    module = graph_module(comp)
    for member in m.members:
        smaller = m.model_copy(update={"members": [x for x in m.members if x is not member]})
        assert mermaid(module.blank(REGISTRY, smaller))
    assert mermaid(module.blank(REGISTRY, m.model_copy(update={"members": []})))


@pytest.mark.parametrize("comp", PANELS)
def test_the_panel_validates_with_no_errors(comp: Component):
    assert [str(p) for p in REGISTRY.validate() if p.where == f"panel {comp.manifest.id}" and p.level == "error"] == []


@pytest.mark.parametrize("pattern", PATTERNS)
def test_a_new_panel_of_any_pattern_is_written_whole_and_compiles(pattern: str, tmp_path: Path):
    from hiru_ai.cli.main import main
    from hiru_ai.core.registry import Registry

    assert main(["--root", str(tmp_path), "new", "panel", "demo", "--pattern", pattern]) == 0
    reg = Registry(tmp_path).discover()
    assert not reg.errors
    graph = reg.module("panel", "demo", "graph")
    assert mermaid(graph.blank())
    problems = [p for p in reg.validate() if p.level == "error"]
    needs = mf.PATTERN_ROLES.get(pattern, {})
    assert len(problems) <= len(needs) + 1 and all("TODO" in str(p) or "needs" in str(p) or "does not exist" in str(p)
                                                    for p in problems), [str(p) for p in problems]
