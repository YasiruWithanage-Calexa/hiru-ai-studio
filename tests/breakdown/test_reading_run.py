"""plan/2026-11-15 phases 3-5: the reading drives the breakdown. The model calls are scripted with the breakdown_read
agent's eval case (a length on its own line, a `Name:` speaker label, a heading glued to the sentence before it): no
model, no network. The episode call is left failing (the run is absent-safe there), so these tests see exactly what the
reading changes: the cuts, the heading words, the lengths, the fact lines, the questions and the stops."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.breakdown import checks, fill, packet, reading
from contracts.breakdown import run as brun
from contracts.breakdown.lines import Doc
from contracts.breakdown.schema import Breakdown, ContinuityW, EpisodeW, Scene, SplitW

CASE = yaml.safe_load((Path(__file__).resolve().parents[2] / "src" / "libs" / "hiru_ai" / "agents" / "breakdown"
                       / "breakdown_read" / "evals" / "cases.yaml").read_text(encoding="utf-8"))[0]
STORY = {"kind": "story_script", "kind_why": "a script", "language_of_dialogue": "Sinhala",
         "text_quality": {"readable": True, "problems": []}}


class Scripted:
    def __init__(self, probe: dict[str, Any] | None = None, reply: dict[str, Any] | None = None) -> None:
        self.asked: dict[str, list[str]] = {k: [] for k in ("probe", "read", "split", "continuity", "episode")}
        self.probe_reply, self.read_reply = probe or STORY, reply or CASE["reply"]

    def calls(self) -> brun.Calls:
        def no_model(msg: str) -> EpisodeW:
            self.asked["episode"].append(msg)
            raise RuntimeError("not scripted")

        return brun.Calls(
            probe=lambda m: self._got("probe", m, reading.ProbeW.model_validate(self.probe_reply)),
            read=lambda m: self._got("read", m, reading.ReadingW.model_validate(self.read_reply)),
            split=lambda m: self._got("split", m, SplitW(sections=[], cards=[], rules=[], episodes=[])),
            continuity=lambda m: self._got("continuity", m, ContinuityW.model_validate(brun.EMPTY_CONTINUITY)),
            episode=no_model, repair=no_model)

    def _got(self, slot: str, msg: str, out: Any) -> Any:
        self.asked[slot].append(msg)
        return out


def _upload() -> brun.Upload:
    return brun.Upload(document_id="doc-0001-x", filename="a.pdf", text="\n".join(CASE["lines"]))


def _answered() -> dict[str, dict[str, Any]]:
    return {"breakdown:length:doc0001x:E01-S02": {"text": "25 seconds"}}


def test_a_missing_length_waits_for_a_person_before_anything_else_is_paid_for() -> None:
    s = Scripted()
    res = brun.create([_upload()], s.calls(), workers=1, default_s=60)
    assert res.memory is None and res.failed == ""
    assert [q.key for q in res.questions] == ["breakdown:length:doc0001x:E01-S02"]
    assert res.questions[0].allow_text and res.questions[0].options[0]["value"] == "default"
    assert len(s.asked["probe"]) == 1 and len(s.asked["read"]) == 1
    assert s.asked["split"] == s.asked["continuity"] == s.asked["episode"] == []  # nothing past the reading


def test_with_the_answer_the_reading_drives_the_scenes() -> None:
    s = Scripted()
    res = brun.create([_upload()], s.calls(), workers=1, default_s=60, answers=_answered())
    bd = res.memory
    assert res.failed == "" and bd is not None
    lines = res.sources[0].lines
    assert lines[6:8] == ["He returns to work.", "SCENE 02 — ANUDI ARRIVES"]  # the glued heading on its own line
    one, two = bd.scenes
    assert (one.heading, one.title_doc) == ("SCENE 01 — KASUN'S EVERYDAY LIFE", "KASUN'S EVERYDAY LIFE")
    assert one.stated_s == 30
    assert (two.heading, two.stated_s) == ("SCENE 02 — ANUDI ARRIVES", 25.0)  # the person's answer
    assert one.facts == [3, 4] and two.facts == [9]  # "Location:" / "Duration:" hold no story words
    assert one.last == 7 and two.heading_line == 8
    assert res.sources[0].reading and res.sources[0].reading["scenes"][1]["heading"]["line"] == 8
    assert [fill.envelope_of(sc) for sc in bd.scenes] == [30, 25]  # the scene rows' lengths, from the reading
    assert all(sc.brief is None for sc in bd.scenes)  # the scripted episode call failed: absent-safe, as before


def test_the_default_answer_leaves_the_production_default() -> None:
    res = brun.create([_upload()], Scripted().calls(), workers=1,
                      answers={"breakdown:length:doc0001x:E01-S02": {"value": "default"}})
    assert res.memory is not None and res.memory.scenes[1].stated_s is None


def test_damaged_letters_stop_before_the_reading_is_paid_for() -> None:
    damaged = {**STORY, "text_quality": {"readable": False, "problems": [
        {"where": {"line": 6, "quote": "Kasun:"}, "what": "vowel signs before their letters"}]}}
    s = Scripted(probe=damaged)
    res = brun.create([_upload()], s.calls(), workers=1)
    assert res.memory is None and "Unicode Sinhala font" in res.failed
    assert s.asked["read"] == []


def test_a_document_that_is_no_story_stops() -> None:
    s = Scripted(probe={**STORY, "kind": "cast_or_crew_list", "kind_why": "cast notes only"})
    res = brun.create([_upload()], s.calls(), workers=1)
    assert res.memory is None and "no story" in res.failed and s.asked["read"] == []


def test_a_reading_that_fails_its_checks_twice_stops() -> None:
    bad = {**CASE["reply"], "scenes": [{**CASE["reply"]["scenes"][0], "heading": {"line": 2, "quote": "NOT THERE"}},
                                       CASE["reply"]["scenes"][1]]}
    s = Scripted(reply=bad)
    res = brun.create([_upload()], s.calls(), workers=1)
    assert res.memory is None and "could not be read reliably" in res.failed
    assert len(s.asked["read"]) == 2  # the reading and one repair, then the stop


def test_a_failed_model_call_stops_the_build_no_rules_read_instead() -> None:
    calls = Scripted().calls()
    calls.read = lambda m: (_ for _ in ()).throw(RuntimeError("down"))
    res = brun.create([_upload()], calls, workers=1)
    assert res.memory is None and "could not be read by the model" in res.failed


# ── phase 4: the word check ─────────────────────────────────────────────────────────────────────────────────────


def _scene(blocks: list[dict[str, Any]], facts: list[int]) -> tuple[Breakdown, Doc]:
    doc = Doc(["SCENE 01 — A", "Location: Colombo", "Kasun smiles.", 'Kasun: "Enna."',
               'Father (over the phone): "Hari."'])
    sc = Scene(id="E01-S01", episode=1, number=1, heading="SCENE 01 — A", heading_line=1, first=2, last=5,
               blocks=blocks, facts=facts)
    return Breakdown(document="d", scenes=[sc]), doc


def _block(bid: str, kind: str, line: int, a: int, z: int) -> dict[str, Any]:
    return {"id": bid, "kind": kind, "text": "x y", "speaker": "C01", "spans": [(line, a, z)], "events": []}


def test_a_name_label_before_the_spoken_words_is_the_speaker_not_a_missing_word() -> None:
    blocks = [_block("B1", "action", 3, 0, 2), _block("B2", "dialogue", 4, 1, 2), _block("B3", "dialogue", 5, 4, 5)]
    bd, doc = _scene(blocks, facts=[2])
    assert checks.words(bd, doc) == []


def test_a_fact_line_is_needed_in_no_block_but_other_words_still_are() -> None:
    blocks = [_block("B2", "dialogue", 4, 1, 2), _block("B3", "dialogue", 5, 4, 5)]
    bd, doc = _scene(blocks, facts=[2])
    (f,) = checks.words(bd, doc)
    assert "line 3" in f.message and "Location" not in f.message  # "Kasun smiles." is story; "Location:" is a fact
    bd, doc = _scene([_block("B1", "action", 3, 0, 2), *blocks], facts=[])
    (f,) = checks.words(bd, doc)
    assert "line 2" in f.message  # without the reading's fact lines it would go to repair, as before


def test_the_packet_carries_the_reading_s_length_and_title() -> None:
    sc = Scene(id="E01-S01", episode=1, number=1, heading="SCENE 01 — A", heading_line=1, first=2, last=2,
               brief={"title": "brief title", "summary": "", "purpose": "", "people": [], "things": [], "mood": [],
                      "turns": [], "place": ""}, stated_s=27.6, title_doc="THE DOCUMENT'S TITLE")
    p = packet.assemble(Breakdown(document="d", scenes=[sc]), "E01-S01")
    assert p["H_length"]["stated_seconds"] == 28 and p["A_scene"]["title"] == "THE DOCUMENT'S TITLE"
    assert fill.envelope_of(sc) == 28
