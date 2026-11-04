"""The plan is the legacy engine's, unchanged."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structure_build.engine import looks as legacy

from hiru_ai.steps.look_plan import step

HERE = Path(__file__).resolve().parents[1]


def load() -> dict[str, Any]:
    return json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_rules_only_equals_the_legacy_plan_without_a_model():
    case = load()
    rows, names = legacy.plan(case["canon"], set(), case["episodes"], production_id=case["production_id"],
                              actor=None, ask=None)
    got = step.run(case)
    assert got["rows"] == rows and got["names"] == names == ["Kamala"]  # Nimal has no wardrobe


def test_the_models_looks_equal_the_legacy_plan_with_a_model():
    case = load()
    answer = {"looks": [{"character": "Kamala", "name": "Everyday", "from": 1, "to": 4, "outfit": "Cotton saree",
                         "hair": "", "makeup": "", "accessories": ""}]}
    rows, names = legacy.plan(case["canon"], set(), case["episodes"], production_id=case["production_id"],
                              actor=None, ask=lambda system, user: answer)
    got = step.run({**case, "asked": answer["looks"]})
    assert got["rows"] == rows and got["names"] == names


def test_a_character_with_a_look_is_left_alone():
    assert step.run({**load(), "with_looks": ["c1"]}) == {"rows": [], "names": [], "wanted": []}
