"""The reader's entries against the document: what is not in it is dropped, what is kept is cleaned."""
from __future__ import annotations

from typing import Any

from hiru_ai.steps.memory_check import logic, step

BIBLE = (
    "GENRE    Action / Crime Thriller / Love\n"
    "Love scenes      50mm and 85mm lenses, shallow focus and minimal\n"  # a line break inside the sentence
    "camera movement.\n"
    "Sound      Rain, breathing, metal impacts and footsteps first. Music enters only for hero elevation moments.\n"
    "Slow motion      Use only twice: Nimal's key falling and Dinu removing the gun.\n")


def entry(topic: str = "camera", applies_to: str = "when:love scenes", says: str = "Use 50mm and 85mm.",
          quote: str = "Love scenes 50mm and 85mm lenses, shallow focus", strength: str = "prefer") -> dict[str, Any]:
    return {"topic": topic, "applies_to": applies_to, "says": says, "quote": quote, "strength": strength}


def test_an_entry_that_quotes_the_document_is_kept_whatever_the_line_breaks_and_case():
    out = logic.check([entry(quote="love SCENES 50mm and 85mm lenses, shallow focus and minimal camera movement.")],
                      BIBLE)
    assert [e["topic"] for e in out["entries"]] == ["camera"] and out["dropped"] == 0 and out["warnings"] == []


def test_an_entry_with_a_made_up_quote_is_dropped_and_named():
    out = logic.check([entry(quote="Always shoot in black and white", says="No colour.")], BIBLE)
    assert out["entries"] == [] and out["dropped"] == 1
    assert "quote is not in the document" in out["warnings"][0] and "No colour." in out["warnings"][0]


def test_a_quote_cut_short_or_skipping_a_stretch_with_an_ellipsis_is_read_by_its_pieces_in_order():
    assert logic.check([entry(quote="Love scenes 50mm and 85mm lenses, shallow focus…")], BIBLE)["dropped"] == 0
    assert logic.check([entry(quote="Love scenes 50mm ... camera movement.")], BIBLE)["dropped"] == 0
    assert logic.check([entry(quote="camera movement ... Love scenes 50mm")], BIBLE)["dropped"] == 1  # wrong order


def test_a_quote_too_short_to_mean_anything_is_dropped():
    assert logic.check([entry(quote="the")], BIBLE)["dropped"] == 1
    assert logic.check([entry(quote="")], BIBLE)["dropped"] == 1


def test_an_empty_direction_a_bad_strength_and_a_bad_target_are_dropped():
    out = logic.check([entry(says="  "), entry(strength="should"), entry(applies_to="somewhere nice"),
                       entry(applies_to="episode:two"), entry(applies_to="place:"), entry(topic=" ")], BIBLE)
    assert out["entries"] == [] and out["dropped"] == 6


def test_every_target_form_is_accepted_and_written_in_one_shape():
    forms = ["production", "Place: Colombo", "character:Nimal", "episode: 2", "when: love scenes"]
    out = logic.check([entry(applies_to=f, says=f"say {n}") for n, f in enumerate(forms)], BIBLE)
    assert [e["applies_to"] for e in out["entries"]] == [
        "production", "place:Colombo", "character:Nimal", "episode:2", "when:love scenes"]


def test_a_topic_is_lower_case_with_words_joined():
    out = logic.check([entry(topic="Slow Motion")], BIBLE)
    assert out["entries"][0]["topic"] == "slow_motion"


def test_the_same_direction_twice_is_one_entry_and_two_directions_from_one_line_are_two():
    same = [entry(), entry(says="use 50mm and 85mm.")]
    assert len(logic.check(same, BIBLE)["entries"]) == 1 and logic.check(same, BIBLE)["dropped"] == 0
    quote = "Rain, breathing, metal impacts and footsteps first. Music enters only for hero elevation"
    split = [entry(topic="sound", applies_to="production", says="Rain and breathing first.", quote=quote),
             entry(topic="music", applies_to="when:hero elevation moments", says="Music only here.", strength="must",
                   quote=quote)]
    assert [e["topic"] for e in logic.check(split, BIBLE)["entries"]] == ["sound", "music"]


def test_a_reader_that_lists_the_whole_page_is_capped_and_the_rest_reported():
    many = [entry(says=f"direction {n}") for n in range(logic.MAX_ENTRIES + 5)]
    out = logic.check(many, BIBLE)
    assert len(out["entries"]) == logic.MAX_ENTRIES and out["dropped"] == 5


def test_a_wall_of_dropped_entries_is_summarised_not_listed():
    out = logic.check([entry(quote="nothing like this", says=f"d{n}") for n in range(25)], BIBLE)
    assert out["dropped"] == 25 and len(out["warnings"]) == logic.SHOWN_WARNINGS + 1
    assert out["warnings"][-1] == "15 more memory entries were dropped"


def test_a_sinhala_quote_is_found_in_a_sinhala_document():
    text = "ශබ්ද නිර්දේශය    වැස්ස සහ හුස්ම පළමුව."
    out = logic.check([entry(topic="sound", applies_to="production", quote="වැස්ස සහ හුස්ම පළමුව.")], text)
    assert out["dropped"] == 0


def test_the_step_runs_from_json_and_does_not_touch_its_input():
    payload = {"entries": [entry()], "text": BIBLE}
    out = step.run(payload)
    assert out["dropped"] == 0 and payload["entries"] == [entry()]
