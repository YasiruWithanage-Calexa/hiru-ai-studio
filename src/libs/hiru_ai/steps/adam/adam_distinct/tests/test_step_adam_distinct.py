"""adam_distinct: treatments that differ on purpose (plan/2026-11-04b §10 Phase 3)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.adam.adam_distinct import logic, step

HERE = Path(__file__).resolve().parents[1]


def t(name: str, **edit: Any) -> dict[str, Any]:
    base = {"name": name, "concept": "c", "pov": "Anudi's throughout", "sound_concept": "the world stays the same",
            "size_arc": ["MWS", "MS", "MWS"]}
    return {**base, **edit}


def codes(out: dict[str, Any]) -> list[str]:
    return [i["code"] for i in out["issues"]]


def test_the_example_runs_alone_and_passes():
    out = step.run(json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8")))
    assert out["ok"], out["issues"]
    assert len(out["pairs"]) == 3


def test_three_copies_of_one_idea_are_refused_with_the_axes_they_share():
    out = step.run({"treatments": [t("a"), t("b"), t("c")]})
    assert not out["ok"] and codes(out) == ["alike"] * 3
    assert out["pairs"][0]["differs"] == [] and out["pairs"][0]["same"] == ["size_arc", "pov", "sound_concept"]


def test_one_axis_is_not_enough_two_are():
    one = [t("a"), t("b", size_arc=["WS", "CU", "ECU"]), t("c", size_arc=["MS", "ECU", "MS"])]
    assert "alike" in codes(step.run({"treatments": one}))
    two = [t("a"), t("b", size_arc=["WS", "CU", "ECU"], pov="Dasun's"),
           t("c", size_arc=["MS", "ECU", "MS"], sound_concept="music enters at the turn")]
    out = step.run({"treatments": two})
    # b/c differ on arc, pov and sound; a/b on arc and pov; a/c on arc and sound
    assert out["ok"], out["issues"]


def test_an_arc_differs_by_its_peak_or_by_half_its_places():
    assert logic.arcs_differ(["MWS", "CU", "MWS"], ["MWS", "ECU", "MWS"])  # a different peak
    assert not logic.arcs_differ(["MWS", "CU", "MWS"], ["MWS", "CU", "MWS"])
    assert logic.arcs_differ(["MS", "CU", "CU", "MS"], ["WS", "CU", "MCU", "WS"])  # same peak, half the places differ
    assert not logic.arcs_differ(["MS", "CU", "CU", "MS"], ["MS", "CU", "CU", "WS"])  # one place in four
    assert logic.arcs_differ(["MS", "CU"], ["MS", "CU", "ECU", "WS"])  # longer, with a new peak
    assert not logic.arcs_differ([], ["MS"])  # nothing said cannot differ


def test_words_that_mostly_overlap_say_the_same_thing():
    assert not logic.words_differ("Anudi's, all the way through", "Anudi's, all the way through the scene")
    assert logic.words_differ("Anudi's, then Dasun's", "the father's voice")
    assert not logic.words_differ("", "anything")


def test_names_and_stances_must_be_different_and_the_count_is_checked():
    out = step.run({"treatments": [t("same", stance="intimate"), t("same", stance="intimate"), t("c")]})
    assert {"same_name", "same_stance"} <= set(codes(out))
    assert codes(step.run({"treatments": [t("a")]}))[0] == "count"
    assert step.run({"treatments": [t("a")], "expected": 1})["ok"]


def test_a_malformed_treatment_is_reported_not_raised():
    out = step.run({"treatments": [{"nope": 1}]})
    assert not out["ok"] and codes(out) == ["malformed"]
