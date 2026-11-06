"""Tests that live with the jonathan_pack step (ADR 0006): deleting the folder deletes them. The gold-scene checks are
in
`tests/jonathan`."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.jonathan.jonathan_pack import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_pack_has_the_parts_in_the_order_that_caches_and_the_script_last():
    out = step.run(EXAMPLE)
    text = out["text"]
    assert text.index("<production>") < text.index("<scene>") < text.index("<start_state>") < text.index("<script>")
    assert "<last_shot>" not in text and "line [L4]" in text and out["words"] > 50


def test_a_continuous_link_passes_the_end_state_and_the_last_shot_word_for_word_on():
    last = {"setting": "the bench", "lighting": "low sun"}
    out = step.run({**EXAMPLE, "link": "continuous", "start": EXAMPLE["scene"] and {
        "people": [{"who": "Anudi", "where": "the path", "facing": "away", "holding": "her bag", "look": "kurta"}],
        "props": [], "time": "dusk", "light": "low sun"}, "last_shot_ir": last})
    assert '{"setting":"the bench","lighting":"low sun"}' in out["parts"]["last_shot"]
    assert "the path" in out["parts"]["start"] and "from the canon" not in out["parts"]["start"]
    carry = step.run({**EXAMPLE, "link": "carry", "start": None, "last_shot_ir": {"subjects": [1], "lighting": "x"}})
    assert "lighting" not in carry["parts"]["last_shot"]
