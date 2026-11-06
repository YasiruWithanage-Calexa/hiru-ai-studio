"""plan/2026-11-05c: the story reader against the four documents the plan names (tests/fixtures/prose).

The model is scripted. What is held is the code around it: every quote is checked against the document, the cut agrees
with the reading line for line, and no spoken line is changed or dropped whatever the layout.
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import InMemorySaver

from contracts.jobs import DispatchPayload, JobKind
from hiru_ai.core import llm, parts, story
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeCanon, FakeDocs, FakeFiles, FakeJobs, FakeScenes, FakeStructure
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.canon_extract import graph as canon_graph
from hiru_ai.systems.doc_ingest import graph as ingest_graph
from hiru_ai.systems.structure_build import graph as build_graph

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "prose"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
CHECK = parts.step("story_check")
PROSE = parts.step("prose_cut")
PID = uuid4()
DRAMA, DASUN, FATHER, BIBLE = "three-episode-drama.txt", "phone-call-bible-and-script.txt", \
    "scene-father-on-the-phone.md", "phone-call-story-bible.md"


def text_of(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── what a careful model would answer for each document ────────────────────────────────────────────────────────────


def line(speaker: str, text: str, delivery: str = "") -> dict[str, str]:
    return {"speaker": speaker, "delivery": delivery, "text": text}


def episode(number: int | None, starts: str, ends: str, spoken: list[dict[str, str]], *, title: str = "",
            seconds: int | None = 60) -> dict[str, Any]:
    return {"number": number, "title": title, "starts_with": starts, "ends_with": ends, "duration_s": seconds,
            "kind": "script", "spoken": spoken}


def person(name: str, evidence: str, *, aliases: list[str] | None = None, voice_only: bool = False) -> dict[str, Any]:
    return {"name": name, "aliases": aliases or [], "voice_only": voice_only, "evidence": evidence}


def words(text: str, n: int = 8, *, last: bool = False) -> str:
    found = text.split()
    return " ".join(found[-n:] if last else found[:n])


def drama_reading() -> dict[str, Any]:
    """Found the way a reader would: each `EPISODE n` section, every `Name:` line in it."""
    episodes = []
    for section in PROSE.sections(text_of(DRAMA)):
        blocks = PROSE.by_rules(section)[0]["blocks"]
        spoken = [line(b["speaker"], b["text"]) for b in blocks if b["kind"] == "dialogue"]
        body = section.body.split("\n", 1)[1]  # past "Approx. Duration"
        episodes.append(episode(section.number, words(body), words(body, last=True), spoken, title=section.title))
    return {"contains": ["bible", "script"], "episodes": episodes, "people": [], "ignore": []}


def dasun_reading() -> dict[str, Any]:
    sinhala = "මම ඔබ එනවා දැනගෙන හිටියා."
    return {"contains": ["bible", "script"], "people": [
        person("Anudi", "ANUDI — 25, elegant"), person("Dasun", "DASUN — 27, runs a small tea stall"),
        person("Father", 'Saved in her phone as "Thaththe"', aliases=["Thaththe"], voice_only=True)],
        "ignore": ["Story Bible & Script — Page 2", "Story Bible & Script — Page 3", "Story Bible & Script — Page 4"],
        "episodes": [
            episode(1, "DASUN Smiling Miss You dropped your phone", "Hello, Thaththe?", [
                line("DASUN", "Miss! You dropped your phone.", "smiling"), line("ANUDI", "Oh! Thank you."),
                line("ANUDI", "Hello, Thaththe?", "nervous")], title="The Call"),
            episode(2, "Anudi sits at the stall", sinhala, [
                line("DASUN", "You do not have to go back yet.", "gently"), line("ANUDI", "I know."),
                line("ANUDI", sinhala, "softly")], title="The Wait"),
            episode(3, "Rain taps on the tarpaulin roof", "Then I will be here tomorrow", [
                line("ANUDI", "I will tell him tonight.", "quietly"),
                line("DASUN", "Then I will be here tomorrow.")], title="The Answer")]}


def father_reading() -> dict[str, Any]:
    return {"contains": ["script"], "ignore": [], "people": [
        person("Father", "FATHER (ON THE PHONE)", aliases=["Thaththe"], voice_only=True),
        person("Anudi", "Anudi stands in the rain")],
        "episodes": [episode(None, "The road outside the tea stall, evening", "looks at the café across the road", [
            line("FATHER", "Come home soon. We need to talk.", "on the phone, quietly"),
            line("ANUDI", "I am on my way, Thaththe.", "nervous"),
            line("FATHER", "Do not be late.", "on the phone, firmly")], seconds=None)]}


def bible_reading() -> dict[str, Any]:
    return {"contains": ["bible"], "episodes": [], "ignore": [], "people": [
        person("Anudi", "Anudi**, 25, elegant"), person("Dasun", "Dasun**, 27, runs a tea stall"),
        person("Father", 'Saved in her phone as "Thaththe"', aliases=["Thaththe"], voice_only=True)]}


READINGS = {DRAMA: drama_reading, DASUN: dasun_reading, FATHER: father_reading, BIBLE: bible_reading}


def checked(name: str) -> dict[str, Any]:
    return CHECK.check(READINGS[name](), text_of(name))


def expected_lines(name: str) -> list[str]:
    return [ln["text"] for ep in checked(name)["episodes"] for ln in ep["spoken"]]


# ── Phase 0: the yardstick ─────────────────────────────────────────────────────────────────────────────────────────


def test_today_only_one_of_the_three_story_files_builds_scenes_by_rules():
    built = {name: bool(PROSE.to_cut(text_of(name))) for name in (DRAMA, DASUN, FATHER)}
    assert built == {DRAMA: True, DASUN: False, FATHER: False}
    assert sum(built.values()) == 1  # the baseline: 1 of 3
    assert PROSE.to_cut(text_of(BIBLE)) is None  # a bible with nobody speaking: correctly none
    assert {n: e["builds_today"] for n, e in EXPECTED.items()} == {
        DRAMA: True, DASUN: False, FATHER: False, BIBLE: None}


def test_the_checked_readings_match_what_the_fixtures_hold():
    for name, want in EXPECTED.items():
        got = checked(name)
        assert [e["number"] for e in got["episodes"]] == want["episodes"], name
        assert [len(e["spoken"]) for e in got["episodes"]] == want["spoken"], name
        assert got["dropped"] == {"episodes": 0, "lines": 0, "people": 0} and got["warnings"] == [], name
        if "people" in want:
            assert sorted(p["name"] for p in got["people"]) == sorted(want["people"]), name
    heard = {p["name"]: p["voice_only"] for p in checked(FATHER)["people"]}
    assert heard == {"Father": True, "Anudi": False}


# ── Phase 1 (the reader through the core helper) and Phase 2 (ingest and the cache) ─────────────────────────────────


def models(**routes: list[Any]) -> RoutedChatModel:
    return RoutedChatModel(routes={k.replace("__", "."): v for k, v in routes.items()})


def ingest(name: str, model: RoutedChatModel | None) -> tuple[FakeDocs, FakeFiles, FakeJobs, str]:
    document_id = uuid4()
    docs = FakeDocs([{"id": str(document_id), "production_id": str(PID), "filename": name, "mime_type": "text/plain",
                      "storage_path": "p/f", "confirmed_role": None}])
    files = FakeFiles({("documents", "p/f"): (FIXTURES / name).read_bytes()})
    jobs = FakeJobs()
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.DOC_INGEST, actor_user_id=uuid4(),
                              state={"document_id": str(document_id)})
    ctx = RunContext(ports=replace(Ports(), docs=docs, files=files, jobs=jobs))
    if model is None:
        ingest_graph.run(payload, ctx)
    else:
        with llm.use_models(model):
            ingest_graph.run(payload, ctx)
    return docs, files, jobs, f"{PID}/{document_id}/story.json"


def test_ingest_reads_the_story_once_and_keeps_the_checked_reading_beside_the_text():
    docs, files, jobs, path = ingest(DASUN, models(doc_ingest__story=[dasun_reading()]))
    saved = json.loads(files.objects[("documents", path)])
    assert [len(e["spoken"]) for e in saved["episodes"]] == [3, 3, 2]
    assert saved["sha"] == CHECK.text_sha(text_of(DASUN))
    assert docs.document_rows[0]["status"] == "ready"
    assert any("3 episodes, 8 spoken lines, 3 people" in e.get("text", "") for e in jobs.events)


def test_ingest_without_a_key_or_with_a_reader_that_fails_still_succeeds_and_keeps_no_reading():
    for model in (None, models(doc_ingest__story=[RuntimeError("down")])):
        docs, files, _, path = ingest(DASUN, model)
        assert docs.document_rows[0]["status"] == "ready" and ("documents", path) not in files.objects


def test_a_reading_dropped_lines_are_reported_as_a_warning():
    reading = dasun_reading()
    reading["episodes"][0]["spoken"].append(line("ANUDI", "A line the document never had."))
    _, _, jobs, _ = ingest(DASUN, models(doc_ingest__story=[reading]))
    warned = [e["text"] for e in jobs.events if e["type"] == "warning" and "not in the document" in e.get("text", "")]
    assert warned and "1 spoken line the reader quoted is not in the document; left out." in warned[0]


def test_story_for_loads_a_saved_reading_and_reads_then_keeps_one_for_an_older_document():
    text = text_of(DASUN)
    files = FakeFiles()
    docs = FakeDocs(texts={})
    ctx = RunContext(ports=replace(Ports(), docs=docs, files=files))
    doc = {"filename": DASUN, "text_path": "p/d/extracted.txt"}
    assert story.story_for(ctx, doc, text) is None  # no model: today's rules
    model = models(doc_ingest__story=[dasun_reading()])
    with llm.use_models(model):
        first = story.story_for(ctx, doc, text)
    assert first is not None and ("documents", "p/d/story.json") in files.objects
    docs.texts["p/d/story.json"] = files.objects[("documents", "p/d/story.json")].decode("utf-8")
    with llm.use_models(models()):  # a model that would raise: it is not asked
        assert story.story_for(ctx, doc, text) == first
        assert story.story_for(ctx, doc, text + "\nedited") is None  # the text changed: the saved reading is stale


# ── Phase 3: the structure build ──────────────────────────────────────────────────────────────────────────────────────


def build_setup(name: str, role: str, *, reading: bool = True) -> tuple[RunContext, FakeJobs, FakeStructure, Any]:
    docs_texts = {"p/d1/extracted.txt": text_of(name)}
    if reading:
        docs_texts["p/d1/story.json"] = CHECK.dumps(checked(name))
    docs = FakeDocs([{"id": "d1", "filename": name, "confirmed_role": role, "detected_role": None,
                      "text_path": "p/d1/extracted.txt", "production_id": str(PID)}], docs_texts)
    structure, jobs = FakeStructure(), FakeJobs(status="running", cursor=1)
    scenes = FakeScenes(production={"id": str(PID), "orientation": "horizontal", "settings": {}})
    ports = replace(Ports(), jobs=jobs, docs=docs, canon=FakeCanon(), structure=structure, scenes=scenes,
                    files=FakeFiles())
    payload = DispatchPayload(job_id=uuid4(), kind=JobKind.STRUCTURE_BUILD, actor_user_id=uuid4(), production_id=PID,
                              pipeline=[JobKind.CANON_EXTRACT, JobKind.STRUCTURE_BUILD, JobKind.SCRIPT_SPLIT],
                              cursor=1, state={"build": True})
    return RunContext(production_id=PID, ports=ports), jobs, structure, payload


def episode_of(messages: list[BaseMessage]) -> str:
    content = str(messages[-1].content)
    if "<episode>" not in content:  # not the prose writer: the architect and the looks have no scripted answer
        return "other"
    found = re.search(r"Episode (\d+)", content)
    return f"prose{found.group(1)}" if found else "prose"


def writer(name: str, *, drop_a_line_in: int = -1) -> RoutedChatModel:
    """A scripted `prose_writer`: for each episode, what the reading says (one scene), or with one line lost."""
    routes: dict[str, list[Any]] = {}
    for ep in checked(name)["episodes"]:
        section = PROSE.from_story({"episodes": [ep]})[0]  # type: ignore[index]
        scenes = PROSE.by_lines(section)
        if ep["number"] == drop_a_line_in:
            blocks = scenes[0]["blocks"]
            last = max(i for i, b in enumerate(blocks) if b["kind"] == "dialogue")
            scenes[0]["blocks"] = blocks[:last] + blocks[last + 1:]
        routes[f"prose{ep['number']}" if ep["number"] is not None else "prose"] = [{"scenes": scenes}]
    return RoutedChatModel(routes=routes, choose=episode_of)


def run_build(name: str, role: str, model: RoutedChatModel | None, *, reading: bool = True
              ) -> tuple[list[str], FakeJobs, FakeStructure]:
    ctx, jobs, structure, payload = build_setup(name, role, reading=reading)
    if model is None:
        build_graph.run(payload, ctx, InMemorySaver(), durable=False)
    else:
        with llm.use_models(model):
            build_graph.run(payload, ctx, InMemorySaver(), durable=False)
    return [r["text"] for r in structure.line_rows], jobs, structure


def test_all_three_story_files_build_scenes_with_every_spoken_line_word_for_word():
    for name, role in ((DRAMA, "bible"), (DASUN, "bible"), (FATHER, "script")):
        model = writer(name)
        said, jobs, structure = run_build(name, role, model)
        assert structure.scene_rows, name
        assert said == expected_lines(name), name  # not one line changed, dropped or reordered
        assert sum(1 for e in jobs.events if e["type"] == "warning" and "word for word" in e.get("text", "")) == 0
    assert sum(len(expected_lines(n)) for n in (DRAMA, DASUN, FATHER)) == (6 + 7 + 10) + 8 + 3


def test_the_reader_not_the_name_cue_decides_which_episodes_the_writer_sees():
    model = writer(DASUN)
    run_build(DASUN, "bible", model)
    asked = sorted(str(call[-1].content).split("\n", 1)[0] for call in model.calls
                   if "<episode>" in str(call[-1].content))  # the prose writer's calls: no `Name:` line in this file
    assert asked == ["Episode 1 — The Call", "Episode 2 — The Wait", "Episode 3 — The Answer"]


def test_a_cut_that_loses_a_line_is_replaced_by_a_cut_from_the_readers_lines():
    said, jobs, _ = run_build(DASUN, "bible", writer(DASUN, drop_a_line_in=2))
    assert said == expected_lines(DASUN)  # the writer lost one; the build still has all eight
    assert any("did not keep every spoken line word for word" in e.get("text", "") and "episode 2" in e["text"]
               for e in jobs.events if e["type"] == "warning")


def test_without_a_model_a_saved_reading_still_cuts_from_the_readers_lines():
    said, _, structure = run_build(DASUN, "bible", None)
    assert structure.scene_rows and said == expected_lines(DASUN)


def test_without_a_key_and_without_a_reading_it_is_today_unchanged():
    said, _, structure = run_build(DRAMA, "bible", None, reading=False)
    assert len(said) == 6 + 7 + 10 and structure.scene_rows
    said, _, structure = run_build(DASUN, "bible", None, reading=False)
    assert said == [] and not structure.scene_rows  # still the baseline: this layout needs the reader


def test_a_lone_scene_has_no_episode_so_the_build_asks_which_one_it_is():
    _, _, structure = run_build(FATHER, "script", writer(FATHER))
    assert any(q["key"].startswith("episode:") for q in structure.question_rows.values())


def test_a_bible_with_nobody_speaking_builds_no_scenes_and_a_real_screenplay_never_asks_the_reader():
    said, _, structure = run_build(BIBLE, "bible", models())
    assert said == [] and not structure.scene_rows
    ctx, _, structure, payload = build_setup(DRAMA, "script", reading=False)
    screenplay = "INT. KITCHEN - DAY\n\nKAMALA\nCome.\n\nEXT. HARBOUR - DAY\n\nSUNIL\nNets.\n"
    ctx.ports.docs.texts["p/d1/extracted.txt"] = screenplay
    model = models()
    with llm.use_models(model):
        build_graph.run(payload, ctx, InMemorySaver(), durable=False)
    assert "doc_ingest.story" not in model.phases  # the parser owns it: no reader call


def test_episodes_the_reader_lost_send_the_document_back_to_the_rules():
    reading = drama_reading()
    reading["episodes"][1]["starts_with"] = "a sentence that is not in the document"
    story_ = CHECK.check(reading, text_of(DRAMA))
    assert [e["number"] for e in story_["episodes"]] == [1, 3] and story_["dropped"]["episodes"] == 1
    assert [s.number for s in PROSE.to_cut(text_of(DRAMA), {**story_, "episodes": []}) or []] == [1, 2, 3]
    assert [s.number for s in PROSE.to_cut(text_of(DRAMA), {**story_, "episodes": [], "dropped": {"episodes": 0}})
            or []] == []


# ── Phase 4: the canon reads everything ──────────────────────────────────────────────────────────────────────────


def test_the_canon_sees_the_people_and_the_text_of_a_scene_in_any_layout():
    docs = FakeDocs([{"id": "d1", "filename": FATHER, "confirmed_role": "script", "detected_role": None,
                      "text_path": "p/d1/extracted.txt", "production_id": str(PID)}],
                    {"p/d1/extracted.txt": text_of(FATHER), "p/d1/story.json": CHECK.dumps(checked(FATHER))})
    canon, jobs = FakeCanon(), FakeJobs()
    ports = replace(Ports(), jobs=jobs, docs=docs, canon=canon,
                    scenes=FakeScenes(production={"id": str(PID), "orientation": "horizontal", "settings": {}}))
    card = {"summary": "", "age": "", "gender": "", "appearance": "", "wardrobe": "", "voice": "", "accent": "",
            "look": "", "details": "", "notes": ""}
    reply = {"entities": [
        {"kind": "character", "name": "Father", "code": "", "aliases": ["Thaththe"], "core": True,
         "card": {**card, "summary": "Heard on the phone only"}},
        {"kind": "character", "name": "Anudi", "code": "", "aliases": [], "core": True, "card": card},
        {"kind": "prop", "name": "Phone", "code": "", "aliases": [], "core": False, "card": card},
        {"kind": "prop", "name": "Handbag", "code": "", "aliases": [], "core": False,
         "card": {**card, "notes": "Inferred: \"She puts down her handbag\""}},
        {"kind": "location", "name": "Café", "code": "", "aliases": [], "core": False, "card": card}]}
    model = models(canon_extract__extract=[reply])
    with llm.use_models(model):
        canon_graph.run(DispatchPayload(job_id=uuid4(), kind=JobKind.CANON_EXTRACT, actor_user_id=uuid4(),
                                        production_id=PID, pipeline=[JobKind.CANON_EXTRACT], state={"build": False}),
                        RunContext(production_id=PID, ports=ports), InMemorySaver())
    sent = str(model.calls[0][-1].content)
    assert "FATHER (ON THE PHONE)" in sent  # a script reaches the extractor as text, not only as counted speakers
    assert "- Father (also Thaththe) [heard only]" in sent and "- Anudi" in sent
    assert {e["name"] for e in canon.entity_rows} >= {"Father", "Anudi", "Phone", "Handbag", "Café"}
