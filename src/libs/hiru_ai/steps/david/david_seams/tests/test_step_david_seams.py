"""Tests that live with the david_seams step (ADR 0006): deleting the folder deletes them. The gold-scene checks are in
`tests/david`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.david.david_seams import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_a_scene_that_opens_elsewhere_than_the_one_before_ended_is_found():
    found = step.run(EXAMPLE)["problems"]
    assert found and all(p["code"] == "seam" for p in found) and any(p["fix"] == "repair" for p in found)


def test_an_unlinked_pair_is_only_reported():
    found = step.run({**EXAMPLE, "link": ""})["problems"]
    assert all(p["fix"] == "report" for p in found)


def test_a_look_change_is_worked_out_from_a_start_and_an_end():
    start = EXAMPLE["before"]
    end = json.loads(json.dumps(start))
    end["people"][0]["look"] = "a torn red sari, mud on the hem"
    out = step.run({"start": start, "end": end, "number": 3})
    assert [c["who"] for c in out["look_changes"]] == ["Anudi"]
