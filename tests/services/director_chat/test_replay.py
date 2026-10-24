"""The replay harness in rules mode is a CI gate: every `rules` case must pass with no model."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]


def harness() -> ModuleType:
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("replay_director", ROOT / "scripts" / "replay_director.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["replay_director"] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    return module


def test_every_rules_case_passes_without_a_model():
    report = harness().replay("rules")
    failed = [(c["id"], c["failures"]) for c in report["cases"] if not c["ok"]]
    assert not failed
    floor = json.loads((ROOT / "tests" / "eval" / "director_thresholds.json").read_text(encoding="utf-8"))["rules"]
    assert all(report["pass_rate"][k] >= v for k, v in floor.items())


def test_cases_are_well_formed():
    cases = json.loads((ROOT / "tests" / "eval" / "director_replay.json").read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert {c["split"] for c in cases} == {"tune", "heldout"}
    assert sum(c["split"] == "heldout" for c in cases) >= 5  # an honest held-out number needs cases
    for c in cases:
        assert c["message"].strip() and "expect" in c
