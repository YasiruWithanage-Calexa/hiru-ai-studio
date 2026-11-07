"""Tests that live with the zora_guard step (ADR 0006)."""
from __future__ import annotations

import json
from pathlib import Path

from contracts.zora.ledger import Ledger, Line
from hiru_ai.steps.zora.zora_guard import logic, step

HERE = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))


def test_the_example_loses_its_false_claim_its_card_and_its_offer_to_trim():
    out = step.run(EXAMPLE)
    assert out["reply"] == logic.NO_RECEIPT and not out["confirms"] and out["undo"] == ""


def test_confirmations_undo_and_redo_are_read_in_code():
    assert logic.confirms("do it") and logic.confirms("keep the rest, i confirm it")
    assert not logic.confirms("yes") and logic.agrees("yes")
    assert [logic.undo_asked(m) for m in ("undo that", "Go back.", "redo", "undo the lens and make it wider")] == [
        "undo", "undo", "redo", ""]


def test_a_claim_the_ledger_backs_stays():
    ledger = Ledger(changes=[Line(level="shot", where="S03", text="lens 50mm → 85mm")], attempted=True)
    text = "I've changed S03 to an 85. It isolates her."
    assert logic.guard_reply(text, ledger) == text


def test_the_template_reply_says_what_the_ledger_says_in_its_order():
    ledger = Ledger(attempted=True, undelivered=["the shots' angle"], overruns=["S04: the line needs 9 s."])
    assert logic.template_reply(ledger) == ("Nothing in the plan changed. Asked for, not done yet: the shots' angle. "
                                            "S04: the line needs 9 s.")


def test_the_loop_breaker_sees_the_same_unmet_goal():
    goal = logic.cannot_goal({"route": "Open the next scene"})
    history = [{"kind": "director", "blocks": [{"kind": "text", "text": "x", "goal": goal, "met": False}]}]
    assert logic.repeated(history, goal) and not logic.repeated(history, "cannot:other")
