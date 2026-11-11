"""The prompt_polish step: only descriptive sections go to the writer, and a rewrite that loses a fact is not used."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.prompt_polish import step

EXAMPLE = json.loads((Path(__file__).resolve().parents[1] / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_reference_pictures_are_never_sent_and_each_section_carries_what_it_must_keep():
    req = step.run(EXAMPLE)["request"]
    assert [s["key"] for s in req["sections"]] == ["light", "people"]
    light, people = req["sections"]
    assert "4300K" in light["keep"] and "rain" in light["keep"] and "night" in light["keep"]
    assert {"Dinu", "30", "right", "left"} <= set(people["keep"])


def test_a_rewrite_that_keeps_the_facts_is_used_and_one_that_drops_one_is_not():
    req = step.run(EXAMPLE)["request"]
    answer = {"sections": [
        {"key": "light", "text": "Sodium lamps slide past through the night rain, a mixed 4300K glow on his skin."},
        # lost left and right
        {"key": "people", "text": "Dinu, 30, sits in the driver's seat, a red thread on his wrist."}]}
    out = step.run({"op": "merge", "request": req, "answer": answer})
    assert list(out["texts"]) == ["light"] and out["record"]["light"]["text"].startswith("Sodium lamps")
    assert out["kept_code"]["people"].startswith("dropped") and "“right”" in out["kept_code"]["people"]
    assert [c["tone"] for c in out["checks"]] == ["pass", "advisory"]
    assert out["checks"][1]["label"].startswith("People kept as written: the rewrite dropped")
