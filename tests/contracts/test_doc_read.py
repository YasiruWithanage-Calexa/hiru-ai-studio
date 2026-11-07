"""The document reader's pure parts (plan/2026-11-06f Phase 1-2): the format, the text-quality score, the pieces, the
checks, the patch, and the run with fake model calls. The fixtures are the person's two files: Ekama Sakshiya's text
in full, and a skeleton of Avasana Sangnawa (each page's edges and every heading line; its text layer is scrambled)."""
from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from contracts.doc_read import (
    BlockW,
    CanonRead,
    CanonW,
    CharacterW,
    EpisodeW,
    PageW,
    PatchW,
    PieceRead,
    Reading,
    SceneReplaceW,
    SceneW,
    reading_path,
    roster,
    scene_seconds,
    to_candidates,
    to_parsed,
)
from contracts.doc_read_checks import (
    add_speakers,
    apply_patch,
    check_piece,
    drop_unquoted,
    mend,
    runtime_notes,
)
from contracts.doc_read_quality import boundaries, halves, layout, page_quality, pieces, quality
from contracts.doc_read_run import (
    Calls,
    CanonAsk,
    PieceAsk,
    RepairAsk,
    canon_message,
    is_cut,
    piece_message,
    read_document,
    repair_message,
    transcribed_text,
)
from contracts.screenplay import SCENE_HEADING, page_furniture, parse_document

ROOT = Path(__file__).resolve().parents[1]
EKAMA = (ROOT / "fixtures" / "reader" / "ekama-sakshiya.txt").read_text(encoding="utf-8")
AVASANA = (ROOT / "fixtures" / "reader" / "avasana-skeleton.txt").read_text(encoding="utf-8")
GOLD = json.loads((ROOT / "eval" / "reader" / "gold" / "ekama-sakshiya.json").read_text(encoding="utf-8"))


def gold() -> PieceRead:
    return PieceRead.model_validate(GOLD["answer"])


def no_canon() -> CanonW:
    return CanonW(characters=[], locations=[], props=[])


def person(name: str, *aliases: str, quote: str = "") -> CharacterW:
    return CharacterW(name=name, aliases=list(aliases), code="", core=True, summary="a person", age="", gender="",
                      appearance="", wardrobe="", voice="", accent="", per_episode=[], quote=quote)


# ── the rules (decision 9) ────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rules_read_ekama_headings_and_dash_dialogue():
    doc = parse_document(EKAMA, "ekama_sakshiya_screenplay.pdf")
    scenes = doc.scenes
    assert len(scenes) == 9
    assert sum(1 for s in scenes for b in s.blocks if b.kind == "dialogue") == 20
    first = scenes[0].heading
    assert (first.int_ext, first.location, first.time_of_day, first.stated_seconds) == ("EXT", "MAHAWEWA CANAL",
                                                                                         "DAWN", 60)
    assert scenes[1].heading.stated_seconds == 90
    assert scenes[2].heading.flashback and scenes[2].heading.location == "COLOMBO GARAGE"
    assert all(s.heading.time_of_day for i, s in enumerate(scenes) if i != 2)  # scene 3's heading gives no time
    speakers = {sp for s in scenes for sp in s.speakers}
    assert speakers == {"ARUNI", "DINU", "NIMAL", "SUREN", "MUDALALI"}
    assert scenes[0].blocks[1].text == "Dinu... oyata meka ahenne nadda?"


def test_a_page_header_is_never_a_speaker_or_a_scene_line():
    assert "ekama sakshiya" in page_furniture(EKAMA)
    doc = parse_document(EKAMA)
    blocks = [b for s in doc.scenes for b in s.blocks]
    assert not any(b.speaker == "EKAMA SAKSHIYA" or "SCREENPLAY / VISUAL TREATMENT" in b.text for b in blocks)
    assert "TITLE: EKAMA SAKSHIYA" in doc.scenes[0].blocks[-1].text  # the title card is the script's, and stays


def test_a_dash_line_that_wraps_keeps_its_words_and_one_that_ends_hands_back_to_action():
    doc = parse_document("SCENE 1 - INT. ROOM - DAY\n\nARUNI - This line is long and wraps\nonto the next line.\n"
                         "She leaves.\n")
    blocks = doc.scenes[0].blocks
    assert [(b.kind, b.text) for b in blocks] == [("dialogue", "This line is long and wraps onto the next line."),
                                                  ("action", "She leaves.")]


@pytest.mark.parametrize(("line", "want"), [
    ("INT. KAMALA'S HOUSE - KITCHEN - NIGHT", ("INT", "KAMALA'S HOUSE", "KITCHEN", "NIGHT", 0, False, "")),
    ("SCENE 03 - FLASHBACK - INT. COLOMBO GARAGE - 2 MINUTES", ("INT", "COLOMBO GARAGE", "", "", 120, True, "")),
    ("SCENE 02 - INT. CASH VAN - COLOMBO - NIGHT - 1.5 MINUTES",
     ("INT", "CASH VAN", "COLOMBO", "NIGHT", 90, False, "")),
    ("4. INT. SAFEHOUSE / BEDROOM — — 05:30", ("INT", "SAFEHOUSE / BEDROOM", "", "", 0, False, "05:30")),
])
def test_headings(line, want):
    from contracts.screenplay import parse_heading

    h = parse_heading(line)
    assert (h.int_ext, h.location, h.sub_location, h.time_of_day, h.stated_seconds, h.flashback, h.clock) == want


# ── text quality and pieces ───────────────────────────────────────────────────────────────────────────────────────────


def test_scrambled_sinhala_is_found_and_clean_text_is_not():
    assert quality(EKAMA.split("\f")).mode == "text"
    assert quality(AVASANA.split("\f")).mode == "pages"
    assert page_quality(1, "කොළඹ නගරයේ තනිව ජීවත් වන අරවින්ද රේඩියෝ පණිවිඩයක් අසයි").share == 0
    assert page_quality(1, "බෙක7ළඹ නගරබෙw තනිව ජීවM වන අරවින්ද ගුවන්විදුලි").corrupt


def test_the_corpus_sinhala_is_clean():
    corpus = (ROOT / "fixtures" / "corpus" / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8")
    assert quality([corpus]).corrupt_pages == []


def test_avasana_splits_into_its_thirty_episodes():
    doc = layout(AVASANA)
    found = boundaries(doc)
    assert [b.episode for b in found] == list(range(1, 31))
    assert found[0].title == "11:17"
    plan = pieces(doc, role="script")
    assert plan[0].kind == "front" and plan[0].last_line == found[0].line - 1
    assert [p.episode for p in plan[1:]] == list(range(1, 31))
    assert all(a.last_line + 1 == b.first_line for a, b in pairwise(plan))


def test_a_short_document_is_one_call_and_a_long_one_without_episodes_is_windows():
    assert [p.kind for p in pieces(layout(EKAMA), role="script")] == ["whole"]
    long = "\f".join(f"page {n}\nsome words" for n in range(1, 31))
    plan = pieces(layout(long), role="script")
    assert {p.kind for p in plan} == {"window"}
    assert all(b.first_page == a.last_page for a, b in pairwise(plan))  # one page shared
    assert [p.kind for p in pieces(layout(long), role="bible")] == ["front"]


def test_halves_cut_at_the_scene_heading_nearest_the_middle():
    doc = layout(EKAMA)
    whole = pieces(doc, role="script")[0]
    a, b = halves(whole, doc, lambda ln: bool(SCENE_HEADING.match(ln))) or (None, None)
    assert a and b and a.last_line + 1 == b.first_line
    assert SCENE_HEADING.match(doc.lines[b.first_line - 1])


# ── checks ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def ekama_piece():
    doc = layout(EKAMA)
    return doc, pieces(doc, role="script")[0], page_furniture(EKAMA)


def test_the_gold_passes_every_check():
    doc, piece, furniture = ekama_piece()
    assert check_piece(gold(), piece, doc, "text", furniture) == []


def test_a_reworded_line_is_found_word_for_word():
    doc, piece, furniture = ekama_piece()
    answer = gold()
    answer.episodes[0].scenes[0].blocks[1].text = "Dinu, can you not hear this?"  # translated
    problems = check_piece(answer, piece, doc, "text", furniture)
    assert len(problems) == 1 and "not the words of L0050" in problems[0].sentence
    assert problems[0].scene == 0


def test_a_dropped_line_is_found():
    doc, piece, furniture = ekama_piece()
    answer = gold()
    del answer.episodes[0].scenes[3].blocks[2]  # Dinu's "Driver kenek thamai..."
    problems = check_piece(answer, piece, doc, "text", furniture)
    assert any("leaves lines out" in p.sentence and "Driver kenek thamai" in p.sentence for p in problems)


def test_a_time_the_heading_does_not_say_and_one_it_does_but_was_left_out():
    doc, piece, furniture = ekama_piece()
    answer = gold()
    answer.episodes[0].scenes[0].time_of_day = ""
    answer.episodes[0].scenes[2].time_of_day = "NIGHT"  # the flashback heading gives no time
    sentences = [p.sentence for p in check_piece(answer, piece, doc, "text", furniture)]
    assert any("heading says DAWN" in s for s in sentences)
    assert any("NIGHT, which its heading line" in s for s in sentences)


def test_a_skipped_scene_leaves_lines_between_scenes():
    doc, piece, furniture = ekama_piece()
    answer = gold()
    del answer.episodes[0].scenes[4]
    assert any("between two scenes" in p.sentence for p in check_piece(answer, piece, doc, "text", furniture))


def test_pages_mode_checks_the_latin_headings_and_the_transcription():
    doc = layout(AVASANA)
    piece = next(p for p in pieces(doc, role="script") if p.episode == 2)
    heads = [" ".join(doc.lines[n - 1].split()) for n in range(piece.first_line, piece.last_line + 1)
             if SCENE_HEADING.match(doc.lines[n - 1])]
    assert len(heads) > 5
    scenes = [SceneW(number=str(i), heading=h, int_ext="", location="somewhere", sub_location="", time_of_day="",
                     clock="", stated_seconds=0, flashback=False, lines=[], blocks=[]) for i, h in enumerate(heads)]
    pages = [PageW(page=p, text="words") for p in range(piece.first_page, piece.last_page + 1)]
    answer = PieceRead(canon=no_canon(), episodes=[EpisodeW(number=2, title="", stated_runtime="", scenes=scenes)],
                       transcription=pages)
    assert check_piece(answer, piece, doc, "pages", set()) == []
    del answer.episodes[0].scenes[3]
    answer.transcription.pop()
    sentences = [p.sentence for p in check_piece(answer, piece, doc, "pages", set())]
    assert any("missing from the answer" in s for s in sentences)
    assert any(f"No transcription for page {piece.last_page}" in s for s in sentences)


def test_the_wrong_episode_is_a_problem():
    doc = layout(AVASANA)
    piece = next(p for p in pieces(doc, role="script") if p.episode == 2)
    answer = PieceRead(canon=no_canon(), episodes=[EpisodeW(number=3, title="", stated_runtime="", scenes=[])],
                       transcription=[])
    sentences = [p.sentence for p in check_piece(answer, piece, doc, "pages", set())]
    assert any("no episode 2" in s for s in sentences) and any("episode 3, which" in s for s in sentences)


def test_mend_drops_a_page_header_cue_and_gives_a_speaker_its_cue():
    answer = gold()
    blocks = answer.episodes[0].scenes[0].blocks
    blocks.append(BlockW(kind="dialogue", speaker="", cue="EKAMA SAKSHIYA", delivery="", text="x", src=[51, 51]))
    blocks[1].speaker = ""
    fixed = mend(answer, page_furniture(EKAMA))
    assert fixed.answer.episodes[0].scenes[0].blocks[1].speaker == "ARUNI"
    assert len(fixed.answer.episodes[0].scenes[0].blocks) == 3
    assert "page header" in fixed.notes[0]


def test_a_quote_not_in_the_text_loses_the_description_and_keeps_the_name():
    canon = gold().canon
    canon.characters[0].quote = "a quote that is nowhere"
    fixed, notes = drop_unquoted(canon, EKAMA)
    assert fixed.characters[0].name == "Dinu" and fixed.characters[0].summary == ""
    assert fixed.characters[1].summary  # Aruni's quote is in the text
    assert len(notes) == 1


def test_a_new_speaker_becomes_a_supporting_character():
    canon = CanonW(characters=[person("Aruni", "ARUNI")], locations=[], props=[])
    fixed, notes = add_speakers(canon, gold().episodes)
    names = {c.name for c in fixed.characters}
    assert {"Dinu", "Nimal", "Suren", "Mudalali"} <= names
    assert not next(c for c in fixed.characters if c.name == "Dinu").core
    assert len(notes) == 4


def test_runtime_is_reported_never_fixed():
    episodes = gold().episodes
    assert runtime_notes(episodes) == []  # 15 min stated, 15 min 30 s in the headings: close enough
    episodes[0].stated_runtime = "45 MIN"
    assert "add up to 15 min 30 s" in runtime_notes(episodes)[0]


def test_a_patch_replaces_inserts_and_removes_runs_and_refuses_outside():
    answer = gold()
    s = answer.episodes[0].scenes
    patch = PatchW(replaces=[SceneReplaceW(episode=0, replace_from=1, replace_to=1, scenes=[s[1], s[1]]),
                             SceneReplaceW(episode=0, replace_from=8, replace_to=8, scenes=[])])
    fixed = apply_patch(answer, patch)
    assert fixed is not None and len(fixed.episodes[0].scenes) == 9
    assert apply_patch(answer, PatchW(replaces=[SceneReplaceW(episode=0, replace_from=20, replace_to=20,
                                                              scenes=[])])) is None
    assert apply_patch(answer, PatchW(replaces=[SceneReplaceW(episode=7, replace_from=1, replace_to=1,
                                                              scenes=[])])) is None


# ── format ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def reading() -> Reading:
    g = gold()
    return Reading(filename="ekama_sakshiya_screenplay.pdf", source="text", canon=g.canon, episodes=g.episodes)


def test_a_reading_becomes_the_parsers_shape_with_canon_names():
    parsed = to_parsed(reading())
    assert parsed.episodes[0].number is None  # 0: the document does not say
    assert len(parsed.scenes) == 9
    assert {sp for s in parsed.scenes for sp in s.speakers} == {"Aruni", "Dinu", "Nimal", "Suren", "Mudalali"}
    assert parsed.scenes[0].heading.stated_seconds == 60
    assert scene_seconds(reading())["0"] == [60, 90, 120, 150, 90, 90, 60, 180, 90]


def test_a_reading_becomes_canon_candidates_with_counts():
    cands = {c["name"]: c for c in to_candidates(reading())}
    assert cands["Dinu"]["kind"] == "character" and cands["Dinu"]["core"]
    assert cands["Dinu"]["card"]["age"] == "30" and cands["Dinu"]["card"]["gender"] == "male"
    assert cands["Aruni"]["lines"] == 8
    assert cands["C-17 key"]["kind"] == "prop"
    assert cands["Mahawewa Canal"]["kind"] == "location" and cands["Mahawewa Canal"]["scenes"] == 1


def test_a_stored_reading_round_trips_and_an_unknown_one_is_ignored():
    r = reading()
    assert Reading.loads(r.dumps()) == r
    assert Reading.loads("{\"format\": 99}") is None
    assert Reading.loads("not json") is None
    assert reading_path("p/d/extracted.txt") == "p/d/reading.json"


def test_the_roster_has_names_aliases_and_codes_only():
    text = roster(gold().canon)
    assert "PERSON Dinu (also: DINU)" in text and "30" not in text


# ── the run, with fake model calls ───────────────────────────────────────────────────────────────────────────────────


class Fake:
    def __init__(self, pieces_: list[object], repairs: list[object] | None = None,
                 canon: CanonRead | None = None) -> None:
        self.pieces, self.repairs = list(pieces_), list(repairs or [])
        self.canon_answer = canon or CanonRead(canon=no_canon(), transcription=[])
        self.asked: list[object] = []

    def _next(self, queue: list[object]) -> object:
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def calls(self, pdf: bool = False) -> Calls:
        def canon(ask: CanonAsk) -> CanonRead:
            self.asked.append(ask)
            return self.canon_answer

        def piece(ask: PieceAsk) -> PieceRead:
            self.asked.append(ask)
            return self._next(self.pieces)  # type: ignore[return-value]

        def repair(ask: RepairAsk) -> PatchW:
            self.asked.append(ask)
            return self._next(self.repairs)  # type: ignore[return-value]

        return Calls(canon, piece, repair, (lambda a, b: b"%PDF-1.4 pages") if pdf else None)


def test_ekama_is_one_call_and_the_reading_is_checked_and_mended():
    fake = Fake([gold()])
    result = read_document("ekama_sakshiya_screenplay.pdf", "script", EKAMA, fake.calls())
    assert result.reading is not None and result.calls == 1 and result.warnings == []
    r = result.reading
    assert r.source == "text" and r.unresolved == [] and len(r.episodes[0].scenes) == 9
    ask = fake.asked[0]
    assert isinstance(ask, PieceAsk) and ask.kind == "whole" and "L0050  ARUNI - Dinu" in ask.text
    assert ask.pdf_b64 == ""


def test_a_repair_that_fixes_the_line_is_kept():
    bad = gold()
    bad.episodes[0].scenes[0].blocks[1].text = "Dinu, can you not hear this?"
    fixed_scene = gold().episodes[0].scenes[0]
    patch = PatchW(replaces=[SceneReplaceW(episode=0, replace_from=0, replace_to=0, scenes=[fixed_scene])])
    fake = Fake([bad], [patch])
    result = read_document("e.pdf", "script", EKAMA, fake.calls())
    assert result.reading is not None and result.calls == 2
    assert result.reading.episodes[0].scenes[0].blocks[1].text == "Dinu... oyata meka ahenne nadda?"
    repair = fake.asked[1]
    assert isinstance(repair, RepairAsk) and "not the words of L0050" in repair.problems[0]


def test_a_text_piece_that_stays_wrong_is_read_by_the_rules_and_said_so():
    bad = gold()
    bad.episodes[0].scenes[0].blocks[1].text = "Dinu, can you not hear this?"
    useless = PatchW(replaces=[])
    fake = Fake([bad], [useless, useless])
    result = read_document("e.pdf", "script", EKAMA, fake.calls())
    assert result.reading is not None and result.calls == 3
    assert any("read by the rules" in n for n in result.reading.notes)
    assert sum(1 for s in result.reading.episodes[0].scenes for b in s.blocks if b.kind == "dialogue") == 20


def test_a_cut_answer_is_split_and_joined():
    class LengthFinishReasonError(Exception):
        pass

    g = gold()
    first = g.model_copy(deep=True)
    first.episodes[0].scenes = g.episodes[0].scenes[:5]
    second = g.model_copy(deep=True)
    second.episodes[0].scenes = g.episodes[0].scenes[5:]
    fake = Fake([LengthFinishReasonError("finish_reason length"), first, second])
    assert is_cut(LengthFinishReasonError("x"))
    result = read_document("e.pdf", "script", EKAMA, fake.calls())
    assert result.reading is not None and len(result.reading.episodes[0].scenes) == 9


def test_no_pages_to_read_and_a_scrambled_text_gives_no_reading():
    result = read_document("a.pdf", "script", AVASANA, Fake([]).calls(pdf=False))
    assert result.reading is None and "scrambled" in result.reason and result.warnings


def test_a_failing_canon_call_gives_no_reading():
    fake = Fake([])

    def broken(ask: CanonAsk) -> CanonRead:
        raise RuntimeError("down")

    calls = fake.calls(pdf=True)
    calls.canon = broken
    result = read_document("a.pdf", "script", AVASANA, calls)
    assert result.reading is None and "cast could not be read" in result.reason


def avasana_answer(doc, piece, *, skip: int | None = None) -> PieceRead:
    heads = [" ".join(doc.lines[n - 1].split()) for n in range(piece.first_line, piece.last_line + 1)
             if SCENE_HEADING.match(doc.lines[n - 1])]
    scenes = [SceneW(number=str(i), heading=h, int_ext="", location="place", sub_location="", time_of_day="",
                     clock="", stated_seconds=0, flashback=False, lines=[],
                     blocks=[BlockW(kind="dialogue", speaker="Nisha", cue="නිශා", delivery="V.O.", text="තාත්තේ",
                                    src=[])])
              for i, h in enumerate(heads) if i != skip]
    return PieceRead(canon=no_canon(), episodes=[EpisodeW(number=piece.episode, title="", stated_runtime="45 MIN",
                                                          scenes=scenes)],
                     transcription=[PageW(page=p, text=f"page {p}") for p in range(piece.first_page,
                                                                                    piece.last_page + 1)])


def test_avasana_reads_from_pages_one_call_per_episode_with_the_cast_list():
    doc = layout(AVASANA)
    plan = pieces(doc, role="script")
    episodes = [p for p in plan if p.kind == "episode"]
    answers = {p.episode: avasana_answer(doc, p) for p in episodes}
    answers[5] = avasana_answer(doc, episodes[4], skip=2)
    canon = CanonRead(canon=CanonW(characters=[person("Nisha", "නිශා")], locations=[], props=[]),
                      transcription=[PageW(page=1, text="front")])
    seen: list[PieceAsk] = []

    def piece(ask: PieceAsk) -> PieceRead:
        seen.append(ask)
        return answers[ask.episode]

    def repair(ask: RepairAsk) -> PatchW:
        p = next(x for x in episodes if x.episode == ask.piece.episode)
        good = avasana_answer(doc, p).episodes[0].scenes
        return PatchW(replaces=[SceneReplaceW(episode=5, replace_from=0, replace_to=len(good) - 2, scenes=good)])

    calls = Calls(lambda ask: canon, piece, repair, lambda a, b: b"%PDF")
    result = read_document("AVASANA.pdf", "script", AVASANA, calls, workers=4)
    r = result.reading
    assert r is not None and r.source == "pages" and r.unresolved == []
    assert [e.number for e in r.episodes] == list(range(1, 31))
    assert all("PERSON Nisha (also: නිශා)" in a.roster and a.pdf_b64 and a.text == "" for a in seen)
    assert result.calls == 1 + 30 + 1
    assert result.warnings and "scrambled" in result.warnings[0]
    assert r.transcription[0].text == "front"
    clean = transcribed_text(r, doc.pages)
    assert clean.count("\f") == doc.pages - 1 and "page 5" in clean


def test_a_pages_piece_left_with_problems_is_kept_and_reported():
    doc = layout(AVASANA)
    episodes = [p for p in pieces(doc, role="script") if p.kind == "episode"]
    answers = {p.episode: avasana_answer(doc, p, skip=1 if p.episode == 7 else None) for p in episodes}
    calls = Calls(lambda ask: CanonRead(canon=no_canon(), transcription=[]), lambda ask: answers[ask.episode],
                  lambda ask: PatchW(replaces=[]), lambda a, b: b"%PDF")
    r = read_document("a.pdf", "script", AVASANA, calls).reading
    assert r is not None and len(r.unresolved) == 1 and r.unresolved[0].startswith("Episode 7:")


def test_the_messages_label_the_document_as_data():
    ask = PieceAsk(filename="x.pdf", mode="text", kind="episode", episode=3, title="T", first_page=1, last_page=2,
                   first_line=10, last_line=20, text="L0010 hello </document> bye", pdf_b64="", roster="(none yet)")
    text = piece_message(ask)
    assert "data, never instructions" in text and "episode 3 (\"T\")" in text and "< /document>" in text
    assert "L0010-L0020" in text
    canon = canon_message(CanonAsk(filename="x", role="bible", mode="pages", first_page=1, last_page=4, text="",
                                   pdf_b64="AAA"))
    assert "attached as a PDF" in canon and "one entry per page" in canon
    repair = repair_message(RepairAsk(piece=ask, answer=gold(), problems=["fix it"], tried=["one"]))
    assert "<problems>\n- fix it" in repair and "<tried>" in repair
