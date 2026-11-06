"""Tests that live with the zora_ledger step (ADR 0006)."""
from __future__ import annotations

import json
from pathlib import Path

from hiru_ai.steps.zora.zora_ledger import step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_reports_the_changes_the_refusal_and_what_was_not_done():
    out = step.run(EXAMPLE)
    assert [c["where"] for c in out["ops"]["changes"]] == ["Treatment", "S03"]
    assert out["ops"]["nothing_changed"] is False and out["ops"]["undelivered"] == ["the shots' angle"]
    assert [c.split(" (")[0].split("\n")[0] for c in out["context"]] == [
        "DONE THIS TURN", "REQUESTED BUT NOT APPLIED", "ASKED FOR THIS TURN BUT NOT CHANGED"]
