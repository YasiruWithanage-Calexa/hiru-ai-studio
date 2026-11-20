"""The clock and the sentence splitter (plan/2026-11-20 D1/D2), case for case with the interface: this file reads
`clock_cases.json`, the interface's `src/lib/text/sentences.test.ts` reads its identical `src/lib/veo/clock-cases.json`.
The cases are the two lines `lab/sinhala_pace` measured (each needs at least what Omni took to say it) and E01-S04's
long lines (`lab/line_parts`)."""
import json
from pathlib import Path

import pytest

from contracts import shotplan, timing
from contracts.sentences import body, sentence_breaks, sentences
from contracts.shotplan import Item, line_seconds, shot_clock

CASES = json.loads((Path(__file__).parent / "clock_cases.json").read_text(encoding="utf-8"))


def test_the_constants_are_the_measured_ones():
    assert (shotplan.LEAD_IN_S, timing.SENTENCE_PAUSE_S, shotplan.LINE_GAP_S, shotplan.TAIL_S) == (
        CASES["lead_in_s"], CASES["sentence_pause_s"], CASES["line_gap_s"], CASES["tail_s"])


@pytest.mark.parametrize("case", CASES["lines"], ids=lambda c: c["name"][:40])
def test_a_line_needs_what_the_clock_says(case):
    assert timing.words_in(case["text"]) == case["words"]
    assert sentence_breaks(case["text"]) == case["breaks"]
    assert sentences(case["text"]) == case["parts"]
    item = Item(0, "dialogue", case["text"], "A", None, case["delivery"], "l1")
    assert line_seconds(item) == pytest.approx(timing.spoken_seconds(case["text"], case["delivery"]))
    _, need = shot_clock([item])
    assert round(need, 2) == case["need_s"]
    if "at_least_s" in case:  # what Omni Flash 1.2 took to say it, start to last word
        assert need >= case["at_least_s"]


def test_parts_joined_give_the_line_back():
    for case in CASES["lines"]:
        assert " ".join(sentences(case["text"])) == body(case["text"])


def test_a_line_said_in_parts_pauses_at_the_cut_as_it_would_inside_it():
    case = next(c for c in CASES["lines"] if c["name"].startswith("E01-S04 B12"))
    whole = Item(0, "dialogue", case["text"], "Father", None, "", "l12")
    cut = [Item(i, "dialogue", text, "Father", None, "", "l12", part=i + 1, parts=3, whole=case["text"])
           for i, text in enumerate(case["parts"])]
    assert shot_clock(cut)[1] == pytest.approx(shot_clock([whole])[1])
