"""What the drama is (plan/2026-11-12b): the series reader's message, code's checks, the breakdown memory, the packet,
production memory and the prompts' genre phrase. The model is scripted with a hand answer for the Ekama fixture (its
15-minute version: Genre, Tone and Tagline as labels on their own lines); no model, no network."""

from __future__ import annotations

from typing import Any

import pytest

from contracts.breakdown import fill, packet, series
from contracts.breakdown import run as brun
from contracts.breakdown.schema import SeriesW
from contracts.memory import genre_of
from tests.breakdown import rehearsal
from tests.breakdown.test_breakdown_run import Scripted, _upload


def _field(says: str, quote: str, start: int, end: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"found": True, "says": says, "quote": quote, "lines": {"start": start, "end": end or start}, **extra}


def answer(**override: Any) -> dict[str, Any]:
    """A good answer for the fixture (`rehearsal.doc()` lines 1-21)."""
    a = {
        "genre": _field("An action-driven crime thriller with a love thread.", "Action / Crime Thriller / Love", 12,
                        facets=[{"name": "Action", "weight": "main"}, {"name": "Crime Thriller", "weight": "main"},
                                {"name": "Love", "weight": "thread"}]),
        "tone": _field("Grounded and realistic, with energetic, crowd-pleasing action.",
                       "Grounded South Indian realism with commercial action energy", 16),
        "world": _field("The drama moves between Colombo and Mahawewa village.", "Colombo and Mahawewa village", 14,
                        places=["Colombo", "Mahawewa village", "Kandy"]),
        "theme": _field("Only one person knows the truth.", "Sathya danne ekkenek witharai.", 18, language="si-Latn"),
        "premise": _field("A driver turns on the network behind a crime against his friend, for the woman he loves.",
                          "A Colombo cash-transfer driver steals Rs. 300 million after witnessing his closest friend's "
                          "murder, then returns to his", 20, 21),
        "left_out": [{"quote": "A 15-MINUTE CRIME THRILLER", "lines": {"start": 2, "end": 2},
                      "why": "running time"}],
    }
    a.update(override)
    return a


class WithSeries(Scripted):
    def __init__(self, reply: dict[str, Any] | None = None, *, fail: bool = False) -> None:
        super().__init__()
        self.asked["series"] = []
        self.reply, self.series_fails = reply or answer(), fail

    def series(self, msg: str) -> SeriesW:
        self.asked["series"].append(msg)
        if self.series_fails:
            raise RuntimeError("no model")
        return SeriesW.model_validate(self.reply)

    def calls(self) -> brun.Calls:
        c = super().calls()
        c.series = self.series
        return c


@pytest.fixture(scope="module")
def made() -> tuple[brun.Result, WithSeries]:
    s = WithSeries()
    return brun.create([_upload()], s.calls(), production="ekama", workers=1), s


# ── the message ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_message_sends_the_title_page_and_overview_as_data_with_the_breakdowns_line_numbers(made):
    msg = made[1].asked["series"][0]
    assert msg.startswith('<document filename="ekama.pdf">') and msg.rstrip().endswith("</document>")
    assert "12: Action / Crime Thriller / Love" in msg and "16: Grounded South Indian realism" in msg


def test_the_message_leaves_out_the_direction_and_the_scenes():
    res = brun.create([_upload()], WithSeries().calls(), workers=1)
    src = res.sources[0]
    msg = series.message(res.sources)
    direction = next(x for x in src.split.sections if x.label == "direction")
    story_end = next(x for x in src.split.sections if x.label == "story").lines.end
    assert f"{direction.lines.start + 1}: " not in msg and f"{story_end}: " not in msg
    assert "..." in msg  # the gap is shown


# ── code's checks ───────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_good_answer_is_stored_with_its_facets_places_and_left_out(made):
    bd = made[0].memory
    assert series.facets(bd.series) == ["action", "crime thriller"] and series.facets(bd.series, "thread") == ["love"]
    places = {p["name"]: p["id"] for p in bd.series["world"]["places"]}
    assert places["Colombo"] and places["Mahawewa village"] and places["Kandy"] == ""
    assert any("Kandy" in f.message and not f.blocking for f in bd.findings)
    assert bd.series["premise"]["planner_only"] is True  # its quote says "murder"
    assert bd.series["left_out"][0]["why"] == "running time"


def _check(**override: Any) -> tuple[dict[str, Any], list[Any]]:
    bd = brun.create([_upload()], Scripted().calls(), workers=1).memory
    return series.check(SeriesW.model_validate(answer(**override)), rehearsal.doc(), bd)


def test_a_quote_that_is_not_in_its_lines_is_dropped():
    block, found = _check(tone=_field("Dark and slow.", "Dark noir with long silences", 16))
    assert block["tone"] == {"empty": "the quote is not in lines 16-16"} and found


def test_a_running_time_in_the_readers_words_is_dropped():
    block, _ = _check(genre=_field("A 15-minute crime thriller.", "Action / Crime Thriller / Love", 12,
                                   facets=[{"name": "crime thriller", "weight": "main"}]))
    assert "says" not in block["genre"]


def test_a_gated_word_in_the_readers_words_is_dropped():
    block, found = _check(premise=_field("A driver sees a murder.", "A Colombo cash-transfer driver", 20))
    assert "says" not in block["premise"] and any("gated" in f.message for f in found)


def test_a_facet_that_is_not_in_its_quote_is_dropped():
    block, found = _check(genre=_field("A thriller.", "Action / Crime Thriller / Love", 12,
                                       facets=[{"name": "noir", "weight": "main"},
                                               {"name": "crime thriller", "weight": "main"}]))
    assert series.facets(block) == ["crime thriller"] and any("'noir'" in f.message for f in found)


def test_a_field_the_documents_do_not_give_is_empty_not_guessed():
    block, _ = _check(theme={"found": False, "says": "", "quote": "", "lines": {"start": 1, "end": 1}})
    assert block["theme"] == {"empty": "not stated"}


# ── absent-safe ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_failed_series_call_keeps_the_build_and_every_packet_as_before():
    res = brun.create([_upload()], WithSeries(fail=True).calls(), workers=1)
    bd = res.memory
    assert bd is not None and bd.series is None
    assert any("genre and tone could not be read" in n for n in res.notes)
    assert all("J_series" not in packet.assemble(bd, sc.id) for sc in bd.scenes)


def test_without_a_series_call_nothing_is_asked_and_nothing_is_stored():
    s = Scripted()
    bd = brun.create([_upload()], s.calls(), workers=1).memory
    assert bd.series is None and "series" not in s.asked


def test_an_answer_with_nothing_found_stores_no_block():
    none = {"found": False, "says": "", "quote": "", "lines": {"start": 1, "end": 1}}
    res = brun.create([_upload()], WithSeries({k: none for k in series.FIELDS}).calls(), workers=1)
    assert res.memory.series is None and any("do not say" in n for n in res.notes)


# ── the packet ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_every_packet_carries_the_same_series_and_its_own_scene(made):
    bd = made[0].memory
    parts = [packet.assemble(bd, sc.id)["J_series"] for sc in bd.scenes]
    shared = [{k: v for k, v in p.items() if k != "this_scene"} for p in parts]
    assert all(x == shared[0] for x in shared) and "left_out" not in shared[0]
    assert all(p["this_scene"]["place"] for p in parts)
    assert any(p["this_scene"]["region"] for p in parts)  # a set inside Colombo or Mahawewa names its region


def test_the_series_never_makes_a_packet_wait(made):
    bd = made[0].memory
    for sc in bd.scenes:
        p = packet.assemble(bd, sc.id)
        without = {k: v for k, v in p.items() if k != "J_series"}
        assert packet.incomplete(bd, p) == packet.incomplete(bd, without) == []


# Raphael's rendering of J_series: tests/raphael/test_series_packet.py (only raphael folders import Raphael).


# ── production memory and the genre phrase ──────────────────────────────────────────────────────────────────────────


def test_the_series_is_written_as_facts_and_the_planner_only_premise_is_not(made):
    bd = made[0].memory
    rows = [r for rs in fill.memory_rows(bd).values() for r in rs if r["topic"] == "series"]
    says = [r["says"] for r in rows]
    assert says[0].startswith("Genre: action, crime thriller; love as a thread. ")
    assert all(r["strength"] == "fact" and r["applies_to"] == "production" for r in rows)
    assert not any(s.startswith("Premise") for s in says) and any(s.startswith("Tone: ") for s in says)
    assert len([r for rs in fill.memory_rows(bd).values() for r in rs if r["topic"] != "series"]) == len(bd.rules)


def _row(says: str, **extra: Any) -> dict[str, Any]:
    return {"topic": "series", "applies_to": "production", "says": says, "quote": "", "status": "draft",
            "source": "reader", **extra}


def test_the_genre_phrase_comes_from_the_genre_row(made):
    rows = [{**r, "status": "draft", "source": "reader"} for rs in fill.memory_rows(made[0].memory).values()
            for r in rs]
    assert genre_of(rows) == "action and crime thriller"


def test_a_persons_genre_wins_and_a_rejected_one_is_never_used():
    rows = [_row("Genre: action, crime thriller."), _row("Genre: family drama", source="person")]
    assert genre_of(rows) == "family drama"
    assert genre_of([_row("Genre: family drama", status="rejected"), _row("Genre: crime thriller.")]) == \
        "crime thriller"


def test_a_genre_with_a_number_or_a_gated_word_or_none_keeps_the_general_wording():
    assert genre_of([_row("Genre: 15-minute thriller")]) == ""
    assert genre_of([_row("Genre: murder mystery")]) == ""
    assert genre_of([_row("Tone: dark", topic="tone")]) == "" and genre_of([]) == ""


def test_a_person_may_write_just_the_genre():
    assert genre_of([_row("family drama", quote="Genre: family drama", source="person")]) == "family drama"
