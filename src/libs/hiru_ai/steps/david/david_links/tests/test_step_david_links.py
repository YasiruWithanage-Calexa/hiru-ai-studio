"""Tests that live with the david_links step (ADR 0006): deleting the folder deletes them. The gold-scene checks are in
`tests/david`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.david.david_links import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_a_continuous_scene_joins_the_chain_of_the_one_before():
    out = step.run(EXAMPLE)
    assert out["links"] == {"s1": "", "s2": "continuous", "s3": ""} and out["chains"] == [["s1", "s2"], ["s3"]]


def test_episode_order_links_every_pair_and_a_person_can_unlink_one():
    assert step.run({**EXAMPLE, "order": "episode"})["links"]["s3"] == "carry"
    assert step.run({**EXAMPLE, "overrides": {"s2": "none"}})["links"]["s2"] == ""
