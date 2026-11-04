from __future__ import annotations

from hiru_ai.steps.verbatim_check import step

WRITTEN = "Change Kamala's line to: “I won't sell the boat… not ever.” please"


def ok(op: dict) -> bool:
    return bool(step.run({"op": op, "written": WRITTEN})["ok"])


def test_the_persons_own_words_pass_in_any_case_or_quote_style():
    assert ok({"op": "block.set", "value": "I won't sell the boat... NOT ever."})


def test_a_word_they_never_wrote_fails():
    assert not ok({"op": "block.set", "value": "I will sell the boat"})


def test_a_removal_carries_no_words():
    assert ok({"op": "block.remove"})


def test_a_typo_of_their_word_is_theirs_but_a_short_stranger_is_not():
    assert ok({"op": "block.set", "value": "I won't sell the boaat"})
    assert not ok({"op": "block.set", "value": "cat"})
