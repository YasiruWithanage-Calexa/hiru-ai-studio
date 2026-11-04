"""Generated contract tests for every system (plan/2026-11-03 §5.8, Phase 6): it validates, compiles, draws itself, and
its wiring is snapshot-tested. Nothing is listed by hand: a new system folder is picked up the moment it exists."""
from __future__ import annotations

import os

import pytest

from contracts.jobs import JobKind
from hiru_ai.core import manifest as mf
from hiru_ai.core.patterns import mermaid
from hiru_ai.core.registry import Component, default

REGISTRY = default()
SYSTEMS = [pytest.param(c, id=c.manifest.id) for (k, _), c in sorted(REGISTRY.components.items()) if k == "system"]
UPDATE = os.environ.get("HIRU_AI_UPDATE") == "1"


@pytest.mark.parametrize("comp", SYSTEMS)
def test_the_system_validates_and_serves_a_job_kind(comp: Component):
    m = comp.manifest
    assert isinstance(m, mf.SystemManifest)
    assert [str(p) for p in REGISTRY.validate() if p.where == f"system {m.id}" and p.level == "error"] == []
    # a system that is a stream and not a job (the director chat) serves no kind
    assert m.job_kind == "" or m.job_kind in {k.value for k in JobKind}


@pytest.mark.parametrize("comp", SYSTEMS)
def test_the_system_compiles_and_draws_itself(comp: Component):
    drawn = mermaid(REGISTRY.module("system", comp.manifest.id, "graph").blank(REGISTRY))
    assert "__start__" in drawn and "__end__" in drawn


@pytest.mark.parametrize("comp", SYSTEMS)
def test_the_wiring_matches_the_snapshot(comp: Component):
    snapshot = comp.folder / "tests" / "graph.mmd"
    drawn = mermaid(REGISTRY.module("system", comp.manifest.id, "graph").blank(REGISTRY))
    if UPDATE:
        snapshot.write_text(drawn, encoding="utf-8")
    assert snapshot.is_file(), "write the snapshot with HIRU_AI_UPDATE=1 pytest tests/hiru_ai/test_systems_contract.py"
    assert snapshot.read_text(encoding="utf-8") == drawn, "the wiring changed; if on purpose: HIRU_AI_UPDATE=1"


@pytest.mark.parametrize("comp", SYSTEMS)
def test_the_system_names_every_part_it_uses_and_nothing_disabled(comp: Component):
    assert not [p for p in REGISTRY.validate() if p.where == f"system {comp.manifest.id}"]
