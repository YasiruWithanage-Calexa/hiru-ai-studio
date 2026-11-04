"""Replay every recorded case against the engine and compare the whole outcome (plan/2026-11-03 Phase 0).

`PARITY_UPDATE=1 pytest tests/parity` re-records `expected` for the cases that differ; read the
diff before committing, because that diff is a behaviour change.
"""
from __future__ import annotations

from typing import Any

import pytest

from tests.parity.adapters import ADAPTERS, run_case
from tests.parity.cases import all_cases
from tests.parity.harness import UPDATE, dump, load_all, outcome, path_for

FIXTURES = load_all()
ENGINES = ["legacy", "graph"]
# the systems whose `graph` engine exists (plan/2026-11-03 Phase 6): every service
MIGRATED = {"echo", "doc_ingest", "canon_extract", "structure_build", "frame_render", "script_split", "shot_producer",
            "director_chat"}


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize(("service", "name", "fixture"), FIXTURES, ids=[f"{s}/{n}" for s, n, _ in FIXTURES])
def test_the_engine_matches_the_recording(service: str, name: str, fixture: dict[str, Any], engine: str):
    if engine == "graph" and service not in MIGRATED:
        pytest.skip(f"{service} is not migrated yet")
    got = outcome(run_case(service, fixture["input"], fixture["model"], engine))
    if UPDATE and got != fixture["expected"]:
        dump(path_for(service, name), {**fixture, "expected": got})
        return
    assert got == fixture["expected"]


def test_every_service_has_a_fixture_and_every_case_is_recorded():
    recorded = {(s, n) for s, n, _ in FIXTURES}
    wanted = {(s, n) for s, cases in all_cases().items() for n in cases}
    assert wanted == recorded, f"re-record with `python -m tests.parity.record`: {sorted(wanted ^ recorded)}"
    assert {s for s, _ in recorded} == set(ADAPTERS)


def test_the_recorded_input_is_the_case_definition():
    for service, cases in all_cases().items():
        for name, spec in cases.items():
            fixture = next(f for s, n, f in FIXTURES if (s, n) == (service, name))
            assert (fixture["input"], fixture["model"]) == (spec["input"], spec["model"]), f"{service}/{name}"
