from __future__ import annotations

from contracts.screenplay import episode_number_from, parse_document, parse_heading, parse_outline
from tests.services.doc_ingest.conftest import CORPUS

SCRIPT = (CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8")


def test_fixture_script_parses_into_one_episode_of_six_scenes():
    doc = parse_document(SCRIPT, "harbour-lights-ep01-script.fountain")
    assert [(e.number, e.title) for e in doc.episodes] == [(1, "The Return")]
    assert len(doc.scenes) == 6
    first = doc.scenes[0]
    assert first.heading.location == "KAMALA'S HOUSE"
    assert first.heading.sub_location == "KITCHEN" and first.heading.time_of_day == "DAWN"
    kinds = [b.kind for b in first.blocks]
    assert kinds == ["action", "dialogue", "action", "dialogue"]
    nimal = first.blocks[1]
    assert nimal.speaker == "NIMAL" and nimal.delivery == "quietly"
    assert nimal.text == "අම්මේ, මම ආපහු ආවා."  # Sinhala kept as written
    assert doc.scenes[-1].blocks[-1].kind == "cut"


def test_headings():
    h = parse_heading("12. EXT. KALUGALA HARBOUR - BREAKWATER - MORNING")
    assert (h.int_ext, h.location, h.sub_location, h.time_of_day) == (
        "EXT", "KALUGALA HARBOUR", "BREAKWATER", "MORNING")
    h = parse_heading("INT./EXT. BUS - MOVING - NIGHT")
    assert h.int_ext == "INT/EXT" and h.location == "BUS"
    h = parse_heading("SCENE 4")
    assert h.location == "" and h.time_of_day == ""
    assert parse_heading("INT. TEMPLE").time_of_day == ""


def test_forced_cues_colon_dialogue_and_sound():
    text = "INT. HOUSE - NIGHT\n\n@නිමල්\n(softly)\nහරි.\n\nSFX: a dog barks far away\n\nකමලා: (angrily) එපා!\n"
    doc = parse_document(text, known_speakers={"කමලා"})
    blocks = doc.scenes[0].blocks
    first = blocks[0]
    assert (first.kind, first.speaker, first.delivery, first.text) == ("dialogue", "නිමල්", "softly", "හරි.")
    assert (blocks[1].kind, blocks[1].text) == ("sound", "a dog barks far away")
    assert (blocks[2].kind, blocks[2].speaker, blocks[2].delivery) == ("dialogue", "කමලා", "angrily")


def test_colon_lines_are_only_dialogue_for_known_names():
    doc = parse_document("INT. HOUSE - DAY\n\nNote: the lamp is lit.\n")
    assert doc.scenes[0].blocks[0].kind == "action"


def test_cue_extensions_become_delivery():
    doc = parse_document("EXT. ROAD - DAY\n\nKAMALA (V.O.)\nමම එනවා.\n")
    line = doc.scenes[0].blocks[0]
    assert line.speaker == "KAMALA" and line.delivery == "V.O."


def test_episode_headings_split_one_document():
    text = ("Episode 1 — Arrival\n\nINT. A - DAY\n\nx\n\n"
            "Episode 2: Departure\n\nEXT. B - NIGHT\n\ny\n\nEXT. C - DAY\n\nz\n")
    doc = parse_document(text)
    assert [(e.number, e.title, len(e.scenes)) for e in doc.episodes] == [(1, "Arrival", 1), (2, "Departure", 2)]


def test_episode_number_from_filename_or_text():
    assert episode_number_from("no mark here", "drama_ep07_final.pdf") == 7
    assert episode_number_from("කථාංගය 3\n...", "") == 3
    assert episode_number_from("INT. HOUSE - DAY", "notes.txt") is None


def test_outline():
    eps = parse_outline((CORPUS / "harbour-lights-outline.txt").read_text(encoding="utf-8"))
    assert [e.number for e in eps] == [1, 2, 3, 4]
    assert eps[2].title == "Storm Season" and eps[2].synopsis.startswith("A storm keeps the boats")
