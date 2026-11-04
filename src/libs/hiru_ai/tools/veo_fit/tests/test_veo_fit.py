from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.timing import shot_word_target
from hiru_ai.core.context import RunContext
from hiru_ai.tools.veo_fit import tool

CTX = RunContext()


def fit(**kw: object) -> tool.Result:
    return tool.run(tool.Args(**kw), CTX)  # type: ignore[arg-type]


def test_a_short_line_fits_the_shortest_length():
    out = fit(words=8)
    assert out.duration_s == 4 and out.fits and out.over_s == 0 and out.over_words == 0


def test_the_length_is_never_shorter_than_the_speech():
    assert fit(words=9).duration_s == 6  # 9 words need 4.1 s: a 4 s shot would cut it off
    assert fit(words=20).duration_s == 8


def test_a_line_longer_than_the_longest_shot_is_an_overrun_that_is_reported_not_trimmed():
    out = fit(words=30)
    assert not out.fits and out.duration_s == 8 and out.over_s > 0 and out.over_words == 30 - shot_word_target(8)
    assert out.allowed_s == [4, 6, 8]


def test_a_slow_delivery_needs_more_time_than_the_same_words_said_plainly():
    assert fit(words=8, delivery="whispering, halting").duration_s > fit(words=8).duration_s


def test_a_production_with_a_fixed_length_offers_only_that_length():
    out = fit(words=3, fixed_seconds=8)
    assert out.duration_s == 8 and out.allowed_s == [8]


def test_seconds_can_be_given_instead_of_words():
    assert fit(seconds=5.2).duration_s == 6


@pytest.mark.parametrize("seconds", [4, 6, 8])
def test_the_word_targets_are_the_contracts(seconds: int):
    assert fit(seconds=seconds).word_target == shot_word_target(seconds)


def test_there_must_be_something_to_fit():
    with pytest.raises(ValidationError, match="words or the seconds"):
        tool.Args()
