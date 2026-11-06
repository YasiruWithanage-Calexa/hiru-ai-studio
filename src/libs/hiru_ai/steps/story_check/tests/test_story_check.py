"""The reader's quotes against the document: what is kept comes from the source, what is not in it is dropped."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hiru_ai.steps.story_check import logic, step

HERE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parents[6] / "tests" / "fixtures" / "prose"
SCRIPT = (FIXTURES / "phone-call-bible-and-script.txt").read_text(encoding="utf-8")


def line(speaker: str, text: str, delivery: str = "") -> dict[str, str]:
    return {"speaker": speaker, "delivery": delivery, "text": text}


def episode(starts: str, ends: str, spoken: list[dict[str, str]], *, number: int | None = 1,
            kind: str = "script") -> dict[str, Any]:
    return {"number": number, "title": "", "starts_with": starts, "ends_with": ends, "duration_s": None,
            "kind": kind, "spoken": spoken}


def reading(episodes: list[dict[str, Any]], *, ignore: list[str] | None = None,
            people: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"contains": ["script"], "episodes": episodes, "people": people or [], "ignore": ignore or []}


def first_episode(spoken: list[dict[str, str]]) -> dict[str, Any]:
    return episode("DASUN (Smiling) Miss! You dropped your phone", "Hello, Thaththe?", spoken)


def test_an_episode_and_its_lines_are_cut_from_the_source_not_from_the_models_words():
    story = logic.check(reading([first_episode([
        line("DASUN", "Miss, you dropped your phone", "smiling"),  # no "!" and a comma: the document has its own
        line("ANUDI", "oh thank you"),
        line("ANUDI", "Hello Thaththe", "nervous")])]), SCRIPT)
    (ep,) = story["episodes"]
    assert [ln["text"] for ln in ep["spoken"]] == [
        "Miss! You dropped your phone.", "Oh! Thank you.", "Hello, Thaththe?"]
    assert [ln["speaker"] for ln in ep["spoken"]] == ["DASUN", "ANUDI", "ANUDI"]
    assert ep["body"].startswith("DASUN\n(Smiling)") and ep["body"].endswith("Hello, Thaththe?")
    assert story["dropped"] == {"episodes": 0, "lines": 0, "people": 0} and story["warnings"] == []


def test_a_line_that_is_not_in_the_document_is_dropped_and_said_so():
    story = logic.check(reading([first_episode([
        line("DASUN", "Miss! You dropped your phone."),
        line("ANUDI", "I never said this"),
        line("ANUDI", "Oh! Thank you.")])]), SCRIPT)
    assert [ln["text"] for ln in story["episodes"][0]["spoken"]] == ["Miss! You dropped your phone.", "Oh! Thank you."]
    assert story["dropped"]["lines"] == 1
    assert story["warnings"] == ["1 spoken line the reader quoted is not in the document; left out."]


def test_a_line_must_be_whole_words_and_a_short_one_is_not_found_inside_a_longer_word():
    text = "ANUDI\nI know the knot.\nDASUN\nNo."
    story = logic.check(reading([episode("ANUDI I know", "No", [line("DASUN", "No.")])]), text)
    (spoken,) = story["episodes"][0]["spoken"]
    assert spoken["text"] == "No." and story["episodes"][0]["body"].endswith("DASUN\nNo.")
    assert logic.check(reading([episode("ANUDI I know", "No", [line("DASUN", "no")])]), "ANUDI I know\nknow. No.")


def test_repeated_lines_are_found_one_after_the_other():
    text = "A\nYes.\nB\nYes.\nC\nEnd."
    story = logic.check(reading([episode("A Yes", "End", [line("A", "Yes."), line("B", "Yes.")])]), text)
    assert len(story["episodes"][0]["spoken"]) == 2


def test_an_episode_whose_anchor_is_not_in_the_text_is_dropped():
    story = logic.check(reading([
        first_episode([]),
        episode("a sentence that is not there", "Then I will be here tomorrow", [], number=3)]), SCRIPT)
    assert [e["number"] for e in story["episodes"]] == [1] and story["dropped"]["episodes"] == 1
    assert story["warnings"] == ["The reader's start or end of episode 3 is not in the document; it was left out."]


def test_an_episode_listed_out_of_document_order_is_dropped():
    two = episode("Anudi sits at the stall", "Then I will be here tomorrow", [], number=2)
    three = episode("Rain taps on the tarpaulin roof", "Then I will be here tomorrow", [], number=3)
    story = logic.check(reading([three, two]), SCRIPT)
    assert [e["number"] for e in story["episodes"]] == [3] and story["dropped"]["episodes"] == 1


def test_an_episode_that_runs_into_the_next_is_cut_where_the_next_begins():
    two = episode("Anudi sits at the stall", "Then I will be here tomorrow", [], number=2)  # runs on to the end
    three = episode("Rain taps on the tarpaulin roof", "Then I will be here tomorrow", [], number=3)
    story = logic.check(reading([two, three]), SCRIPT)
    assert [e["number"] for e in story["episodes"]] == [2, 3]
    assert "Rain taps" not in story["episodes"][0]["body"] and "Rain taps" in story["episodes"][1]["body"]


def test_a_number_found_twice_keeps_the_longer_slice():
    text = "Contents: Rain falls. End.\n\nBody: Rain falls. Then more rain falls all night long. End."
    short = episode("Rain falls", "End", [])
    long_ = episode("Body Rain falls", "End", [])
    (only,) = logic.check(reading([short, long_]), text)["episodes"]
    assert only["body"].startswith("Body: Rain falls")


def test_what_the_reader_marked_as_not_story_is_cut_out_everywhere_but_never_from_a_spoken_line():
    story = logic.check(reading(
        [episode("EPISODE 1 THE CALL", "Then I will be here tomorrow", [line("ANUDI", "I know.")])],
        ignore=["Story Bible & Script — Page 3", "Story Bible & Script — Page 4", "I know", "Hi"]), SCRIPT)
    body = story["episodes"][0]["body"]
    assert "Page 3" not in body and "Page 4" not in body and "Story Bible & Script" not in body
    assert "I know." in body  # inside a spoken line: kept
    assert story["ignore"] == ["Story Bible & Script — Page 3", "Story Bible & Script — Page 4", "I know"]


def test_a_quote_to_leave_out_that_is_too_short_to_be_safe_is_not_used():
    story = logic.check(reading([episode("A No it", "is so", [])], ignore=["No"]), "A\nNo it is so")
    assert story["episodes"][0]["body"] == "A\nNo it is so"


def test_people_need_a_quote_that_is_in_the_document():
    story = logic.check(reading([], people=[
        {"name": "Father", "aliases": ["Thaththe"], "voice_only": True, "evidence": 'Saved in her phone as "Thaththe"'},
        {"name": "Ghost", "aliases": [], "voice_only": False, "evidence": "the ghost walks"}]), SCRIPT)
    assert [p["name"] for p in story["people"]] == ["Father"] and story["dropped"]["people"] == 1


def test_a_sinhala_line_is_found_whatever_its_quote_marks_and_spacing():
    story = logic.check(reading([episode("ANUDI Softly", "දැනගෙන හිටියා", [
        line("ANUDI", "“මම  ඔබ එනවා දැනගෙන හිටියා”", "softly")])]), SCRIPT)
    (spoken,) = story["episodes"][0]["spoken"]
    assert spoken["text"] == "මම ඔබ එනවා දැනගෙන හිටියා."


def test_a_long_document_is_warned_about():
    story = logic.check(reading([]), SCRIPT, limit=100)
    assert story["warnings"] == ["Only the first 100 characters of this document were read."]


def test_a_saved_reading_is_used_only_for_the_text_it_was_made_from():
    story = logic.check(reading([]), SCRIPT)
    raw = logic.dumps(story)
    assert logic.loads(raw, SCRIPT) == story
    assert logic.loads(raw, SCRIPT + "\nmore") is None
    assert logic.loads("not json", SCRIPT) is None and logic.loads("[1]", SCRIPT) is None


def test_the_reading_is_saved_beside_the_extracted_text():
    assert logic.story_path("prod/doc/extracted.txt") == "prod/doc/story.json"
    assert logic.story_path("extracted.txt") == "story.json"


def test_it_runs_on_its_example():
    example = json.loads((HERE / "examples" / "basic.json").read_text(encoding="utf-8"))
    (ep,) = step.run(example)["story"]["episodes"]
    assert [ln["text"] for ln in ep["spoken"]] == ["Hello, Anudi.", "You came."]
