"""The creation run, the merge of documents, the columns filled from the memory and the one-scene refresh
(plan/2026-11-11
phases 1, 3 and 5). The model calls are scripted with the lab's saved answers for Ekama: no model, no network."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from contracts.breakdown import fill, memory, packet
from contracts.breakdown import run as brun
from contracts.breakdown.schema import (
    BlockW,
    Breakdown,
    ContinuityW,
    EpisodeW,
    PresenceW,
    SceneBriefW,
    SpanW,
    SplitW,
)
from tests.breakdown import rehearsal

GOLD = Path(__file__).resolve().parents[1] / "fixtures" / "breakdown"
_SCENE = re.compile(r"=== (E\d\d-S\d\d)")


def _gold(name: str) -> str:
    return (GOLD / name).read_text(encoding="utf-8")


def _episodes() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for f in ("episode_ekama_s1_s3.json", "episode_ekama_s04_s09.json"):
        for s in json.loads(_gold(f))["scenes"]:
            out[s["scene"]] = s
    return out


REPAIRS = {s["scene"]: s for s in json.loads(_gold("episode_ekama_s99_repairs.json"))["scenes"]}


class Scripted:
    """The lab's answers, by scene. Counts calls so a test can see what was asked."""

    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.asked: dict[str, list[str]] = {"split": [], "continuity": [], "episode": [], "repair": []}
        self.fail = fail or set()
        self.eps = _episodes()

    def calls(self) -> brun.Calls:
        return brun.Calls(split=self.split, continuity=self.continuity, episode=self.episode, repair=self.repair)

    def split(self, msg: str) -> SplitW:
        self.asked["split"].append(msg)
        if "split" in self.fail:
            raise RuntimeError("no model")
        return SplitW.model_validate_json(_gold("split_ekama.json"))

    def continuity(self, msg: str) -> ContinuityW:
        self.asked["continuity"].append(msg)
        if "continuity" in self.fail:
            raise RuntimeError("no model")
        return ContinuityW.model_validate_json(_gold("continuity_ekama.json"))

    def episode(self, msg: str) -> EpisodeW:
        self.asked["episode"].append(msg)
        wanted = _SCENE.findall(msg.split("SCENES TO BREAK DOWN", 1)[1])
        if "episode" in self.fail:
            raise RuntimeError("no model")
        return EpisodeW.model_validate({"scenes": [self.eps[s] for s in wanted if s in self.eps]})

    def repair(self, msg: str) -> EpisodeW:
        self.asked["repair"].append(msg)
        wanted = _SCENE.findall(msg.split("SCENES TO BREAK DOWN", 1)[1])
        return EpisodeW.model_validate({"scenes": [REPAIRS[s] for s in wanted if s in REPAIRS]})


def _upload() -> brun.Upload:
    return brun.Upload(document_id="doc-1", filename="ekama.pdf", text=rehearsal.FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def made() -> tuple[brun.Result, Scripted]:
    s = Scripted()
    return brun.create([_upload()], s.calls(), production="ekama", workers=1), s


def test_the_page_furniture_goes_the_way_the_lab_cut_it():
    lines = memory.strip_furniture(memory.clean_lines(rehearsal.FIXTURE.read_text(encoding="utf-8")))
    assert lines == rehearsal.doc().lines


def test_creation_breaks_down_every_ekama_scene(made):
    res, s = made
    bd = res.memory
    assert res.failed == "" and bd is not None
    assert [x.id for x in bd.scenes] == [f"E01-S0{n}" for n in range(1, 10)]
    assert all(x.brief for x in bd.scenes)
    assert len(s.asked["split"]) == 1 and len(s.asked["continuity"]) == 1
    assert len(s.asked["episode"]) == 2  # nine scenes of one episode: two calls of at most six
    for sc in bd.scenes:
        assert packet.incomplete(bd, packet.assemble(bd, sc.id)) == [], sc.id


def test_the_repair_mends_the_two_scenes_the_checks_stopped(made):
    res, s = made
    asked = {sid for m in s.asked["repair"] for sid in _SCENE.findall(m.split("SCENES TO BREAK DOWN", 1)[1])}
    assert asked == {"E01-S07", "E01-S08"}
    assert not [f for f in res.memory.findings if f.blocking]


def test_the_document_is_data_inside_tags(made):
    _, s = made
    msg = s.asked["split"][0]
    assert msg.startswith('<document filename="ekama.pdf">') and msg.rstrip().endswith("</document>")


def test_continuity_is_kept_on_the_memory_and_used_by_the_packet(made):
    bd = made[0].memory
    a = packet.assemble(bd, "E01-S02")["A_scene"]  # no `cont` passed: the memory's own
    assert a["time"]["story_order"] == 2 and a["before_in_story"]["id"] == "E01-S03"


def test_a_failed_episode_call_leaves_the_scenes_waiting_and_the_production_open():
    s = Scripted(fail={"episode"})
    res = brun.create([_upload()], s.calls(), workers=1)
    assert res.memory is not None and res.failed == ""
    assert all(sc.brief is None for sc in res.memory.scenes)
    assert any("no breakdown yet" in f.message and f.blocking for f in res.memory.findings)
    assert any("breakdown call failed" in n for n in res.notes)


def test_a_failed_continuity_call_is_absent_safe():
    res = brun.create([_upload()], Scripted(fail={"continuity"}).calls(), workers=1)
    assert res.memory.continuity == brun.EMPTY_CONTINUITY
    assert any("story across episodes" in n for n in res.notes)
    assert all(sc.brief for sc in res.memory.scenes)


def test_no_document_read_means_no_memory():
    res = brun.create([_upload()], Scripted(fail={"split"}).calls(), workers=1)
    assert res.memory is None and res.failed


def test_two_documents_are_one_text_and_one_set_of_cards():
    """The same document twice (a bible and a script that both carry the cast): one card per person, the second
    document's scenes are questions, and every pointer of the second lands on its own lines."""
    lines = rehearsal.doc().lines
    split = SplitW.model_validate_json(_gold("split_ekama.json"))
    a = memory.SourceMemory(document_id="a", filename="a.pdf", lines=lines, split=split)
    b = memory.SourceMemory(document_id="b", filename="b.pdf", lines=lines, split=split)
    merged, d, questions = memory.merge([a, b])
    assert len(d) == 2 * len(lines)
    names = [d.text([memory.Span(c.name.line, c.name.w_from, c.name.w_to)]) for c in merged.cards]
    assert len(merged.cards) == len(split.cards) and len(set(names)) == len(names)
    assert len(merged.rules) == 2 * len(split.rules)
    assert sum(len(e.scenes) for e in merged.episodes) == 9
    assert sum("also has this scene" in q for q in questions) == 9
    second = merged.rules[len(split.rules)]
    assert second.lines.start == split.rules[0].lines.start + len(lines)
    parts = memory.parts([a, b])
    assert (parts[1].first, parts[1].last) == (len(lines) + 1, 2 * len(lines))


def test_today_s_columns_come_from_the_memory(made):
    bd = made[0].memory
    st = fill.structure(bd)
    (ep,) = st["episodes"]
    assert ep["number"] == 1 and ep["synopsis"] and ep["doc_ids"] == ["doc-1"]
    s2 = next(s for s in ep["scenes"] if s["number"] == 2)
    phone = [b for b in s2["blocks"] if b["kind"] == "dialogue" and b["delivery"] == "on the phone"]
    assert len(phone) == 1 and phone[0]["text"].startswith("Route eka maru") and phone[0]["speaker"] == "Mudalali"
    assert s2["envelope_s"] >= 4 and s2["title"] == bd.scene("E01-S02").brief["title"]
    assert len(s2["blocks"]) == len(bd.scene("E01-S02").blocks)  # block i is memory block i (staging indexes match)
    cards = {c["name"]: c for c in fill.canon_cards(bd)}
    assert cards["Dinu"]["kind"] == "character" and cards["Dinu"]["card"]["notes"].startswith("details: ")
    rows = fill.memory_rows(bd)
    assert set(rows) == {"doc-1"} and any(r["applies_to"].startswith("place:") for r in rows["doc-1"])


def test_line_ids_follow_the_dialogue_blocks(made):
    sc = made[0].memory.scene("E01-S02")
    spoken = [b["id"] for b in sc.blocks if b["kind"] == "dialogue" and b["speaker"]]
    rows = [{"id": f"line-{i}", "ord": i} for i in range(len(spoken))]
    assert fill.line_map(sc, list(reversed(rows))) == {bid: f"line-{i}" for i, bid in enumerate(spoken)}


def test_staging_takes_the_stager_s_map_shape(made):
    from contracts.breakdown import stage
    from contracts.stagemap import SceneStaging
    from hiru_ai.agents.stager.schema import Output

    bd = made[0].memory
    sc = bd.scene("E01-S08")
    stage.apply(bd, sc, Output.model_validate_json(_gold("stage_ekama_E01-S08.json")))
    got = SceneStaging.model_validate(fill.staging(bd, sc, script_version=3))
    assert got.by == "model" and got.for_version == 3 and got.marks and got.zones


def _fresh() -> tuple[Breakdown, list[memory.SourceMemory]]:
    res = brun.create([_upload()], Scripted().calls(), workers=1)
    return res.memory, res.sources


def test_an_edit_makes_the_scene_stale_and_its_packet_wait():
    bd, _ = _fresh()
    assert not brun.mark_stale(bd, "E01-S03", 0)  # the version it was built for: nothing changes
    bd.scene("E01-S03").script_version = 1
    assert brun.mark_stale(bd, "E01-S03", 2)
    waits = packet.incomplete(bd, packet.assemble(bd, "E01-S03"))
    assert any(w.startswith("stale") for w in waits)


def test_the_one_scene_refresh_reads_the_person_s_words():
    bd, sources = _fresh()
    before = len(memory.doc(sources, bd.person_lines))
    brun.mark_stale(bd, "E01-S03", 2)
    dinu = next(e.id for e in bd.entities if e.name == "Dinu")
    n = before + 1  # the heading goes first, then the person's lines
    place = bd.scene("E01-S03").brief["place"]

    class OneScene:
        def episode(self, msg: str) -> EpisodeW:
            assert f"{n + 1}: Dinu waits by the door." in msg and "=== E01-S03" in msg
            return EpisodeW(
                scenes=[
                    SceneBriefW(
                        scene="E01-S03",
                        title="The Wait",
                        summary="Dinu waits.",
                        purpose="A pause.",
                        place=place,
                        people=[PresenceW(person=dinu)],
                        blocks=[
                            BlockW(kind="action", spans=[SpanW(line=n + 1, w_from=0, w_to=5)]),
                            BlockW(kind="dialogue", speaker=dinu, spans=[SpanW(line=n + 2, w_from=2, w_to=3)]),
                        ],
                    )
                ]
            )

    calls = brun.Calls(split=None, continuity=None, episode=OneScene().episode, repair=None)  # type: ignore[arg-type]
    notes = brun.refresh_scene(
        bd, sources, "E01-S03", ["Dinu waits by the door.", "DINU - Hari."], calls, script_version=2
    )
    sc = bd.scene("E01-S03")
    assert notes == [] and sc.edited and not sc.stale and sc.script_version == 2 and sc.stage is None
    assert [b["text"] for b in sc.blocks] == ["Dinu waits by the door.", "Hari."]
    assert bd.person_lines[0] == sc.heading and sc.heading_line == n
    p = packet.assemble(bd, "E01-S03")
    assert packet.incomplete(bd, p) == []
    assert all(sc2.blocks for sc2 in bd.scenes if sc2.id != "E01-S03")  # the other scenes keep their words
    assert bd.scene("E01-S04").blocks[0]["text"]


def test_a_line_pointed_from_its_cue_names_the_words_it_lost():
    """The live run's S03 slip (2026-11-11): `NIMAL - … walin gaththa salli.` pointed from word 0, so the cue was inside
    the block and the last two spoken words in none. The finding says which words, so a repair can put them back."""
    from contracts.breakdown import build as build_mod
    from contracts.breakdown import checks
    from contracts.breakdown.lines import Doc
    from contracts.breakdown.schema import EpisodeCutW, SceneCutW

    d = Doc(["SCENE 01 - INT. GARAGE - NIGHT", "NIMAL - Village project walin gaththa salli."])
    bd = build_mod.build(SplitW(sections=[], cards=[], rules=[], episodes=[EpisodeCutW(
        number=0, heading=1, scenes=[SceneCutW(number=1, heading=1, last=2)])]), d, "t")
    build_mod.apply_episode(bd, d, EpisodeW(scenes=[SceneBriefW(
        scene="E01-S01", title="t", summary="s", purpose="p", people=[],
        blocks=[BlockW(kind="dialogue", spans=[SpanW(line=2, w_from=0, w_to=5)])])]))
    found = [f.message for f in checks.words(bd, d)]
    assert any("line 2 words 5-6 ('gaththa salli.') in no block" in m for m in found), found
    assert any("starts with the speaker cue" in m for m in found)
