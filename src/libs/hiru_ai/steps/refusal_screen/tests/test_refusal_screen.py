from __future__ import annotations

from hiru_ai.steps.refusal_screen import step
from hiru_ai.steps.refusal_screen.logic import FALLBACK


def test_a_plain_sentence_is_kept():
    assert step.run({"reason": "there is no shot 9"}) == {"text": "there is no shot 9"}


def test_the_codes_own_words_never_reach_a_person():
    for leaked in ("OpError: block.set failed", "value is None", "a {dict} leaked", "takes text", "", "   "):
        assert step.run({"reason": leaked}) == {"text": FALLBACK}, leaked
