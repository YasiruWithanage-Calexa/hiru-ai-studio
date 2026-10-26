"""Prose episodes (no scene headings) become scenes; the model's cut is trusted only if it keeps every line."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "structure_build"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from structure_build.engine import analyse, pipeline, prose  # noqa: E402

from tests.services.fakes import FakeJobs, FakeLLM  # noqa: E402
from tests.services.structure_build.test_structure_build import (  # noqa: E402
    FakeStore,
    build_payload,
    doc,
)

DRAMA = (ROOT / "tests" / "fixtures" / "prose" / "three-episode-drama.txt").read_text(encoding="utf-8")


def character(name: str, code: str) -> dict[str, Any]:
    return {"id": str(uuid4()), "kind": "character", "code": code, "name": name, "aliases": []}


def place(name: str, code: str) -> dict[str, Any]:
    return {"id": str(uuid4()), "kind": "location", "code": code, "name": name, "aliases": []}


def test_episode_sections_carry_title_and_length():
    found = prose.sections(DRAMA)
    assert [(s.number, s.title, s.duration_s) for s in found] == [
        (1, "The First Meeting", 60), (2, "The Difference", 60), (3, "The Choice", 60)]
    assert "END EPISODE" not in found[0].body and "EPISODE 2" not in found[0].body
    assert all(prose.is_script_like(s) for s in found)


def test_a_synopsis_or_a_screenplay_is_left_alone():
    outline = "Episode 1 — The Return\nNimal comes home to find the house empty and his mother gone.\n"
    assert prose.convert(outline, None, []) is None
    screenplay = "EPISODE 1 — X\n\nINT. HOUSE - DAY\n\nKasun:\n“Hi.”\n\nAnudi:\n“Hello.”\n"
    assert prose.convert(screenplay, None, []) is None  # the parser reads real headings itself


def test_rules_keep_every_spoken_line_and_ignore_screen_text():
    converted = prose.convert(DRAMA, None, [])
    assert converted and converted.episodes == [1, 2, 3] and converted.by_model == []
    plan = analyse.analyse([{**doc("pack.pdf", "script", converted.text), "scene_seconds": converted.scene_seconds}],
                           [])
    units = list(plan["units"].values())
    assert [u["number"] for u in units] == [1, 2, 3]
    ep1 = units[0]["scenes"][0]["blocks"]
    spoken = [(b["speaker"], b["text"]) for b in ep1 if b["kind"] == "dialogue"]
    assert spoken[0] == ("Kasun", "Miss! Your phone!") and spoken[-1][0] == "Anudi"
    assert len(spoken) == 6
    final = [b for u in units[2:] for b in u["scenes"][-1]["blocks"] if b["kind"] == "dialogue"]
    assert "FINAL TEXT ON SCREEN" not in {b["speaker"] for b in final}
    assert units[0]["scenes"][0]["envelope_s"] == 60


def good_cut(system: str, user: str) -> dict[str, Any]:
    """What a faithful model returns for episode 1: three scenes, canon names, exact lines."""
    assert "<episode>" in user and "Target length: 60 s" in user
    if "Episode 1" not in user:
        return {"scenes": []}  # the other episodes: nothing usable → rules
    d = lambda who, text: {"kind": "dialogue", "speaker": who, "delivery": "", "text": text}  # noqa: E731
    a = lambda text: {"kind": "action", "speaker": "", "delivery": "", "text": text}  # noqa: E731
    return {"scenes": [
        {"int_ext": "EXT", "location": "Kasun's Food Three-Wheeler", "sub_location": "", "time_of_day": "DAY",
         "seconds": 20, "blocks": [a("Rain over Colombo. Kasun sells short eats."),
                                   d("Kasun", "One day… I'll have my own restaurant,")]},
        {"int_ext": "EXT", "location": "Colombo Road", "sub_location": "", "time_of_day": "DAY", "seconds": 30,
         "blocks": [d("Kasun", "Miss! Your phone!"), d("Anudi", "Oh… thank you."),
                    d("Anudi", "You made all this yourself?"),
                    d("Kasun", "Started with Rs. 5,000. I'm trying to make it bigger."),
                    d("Anudi's Father", "Anudi, where are you? Come home. We need to talk about your marriage."),
                    d("Anudi", "Maybe… I'll see you again.")]},
        {"int_ext": "EXT", "location": "Colombo Road", "sub_location": "", "time_of_day": "DAY", "seconds": 10,
         "blocks": [a("Kasun watches her leave.")]},
    ]}


def test_the_model_cuts_scenes_and_lengths_add_up_to_the_episode():
    canon = [character("Kasun", "C01"), character("Anudi", "C02"), character("Anudi's Father", "C03"),
             place("Kasun's Food Three-Wheeler", "L01"), place("Colombo Road", "L02")]
    prompts: list[str] = []
    converted = prose.convert(DRAMA, lambda system, user: prompts.append(user) or good_cut(system, user), canon)
    assert all("character: Anudi's Father" in p and "location: Colombo Road" in p for p in prompts)
    assert converted and converted.by_model == [1] and converted.fallbacks == [2, 3]
    assert converted.scene_seconds["1"] == [20, 30, 10] and sum(converted.scene_seconds["2"]) == 60
    plan = analyse.analyse([{**doc("pack.pdf", "script", converted.text), "scene_seconds": converted.scene_seconds}],
                           canon)
    ep1 = next(u for u in plan["units"].values() if u["number"] == 1)
    assert [s["heading"]["raw"] for s in ep1["scenes"]] == [
        "EXT. Kasun's Food Three-Wheeler - DAY", "EXT. Colombo Road - DAY", "EXT. Colombo Road - DAY"]
    assert [s["envelope_s"] for s in ep1["scenes"]] == [20, 30, 10]
    ids = {c["id"] for c in canon}
    assert all(s["location"]["id"] in ids for s in ep1["scenes"])
    father = [b for b in ep1["scenes"][1]["blocks"] if b.get("speaker") == "Anudi's Father"]
    assert father and father[0]["character"]["id"] in ids
    # Episode 1 matched the canon exactly; "Father" in the rule-cut episodes is only close to it.
    assert [q["key"] for q in plan["questions"]] == ["spk:father"]


def test_a_model_that_rewords_a_line_is_rejected():
    def reworded(system: str, user: str) -> dict[str, Any]:
        scenes = good_cut(system, user)["scenes"] or good_cut(system, "Episode 1 " + user)["scenes"]
        scenes[1]["blocks"][0]["text"] = "Excuse me, you dropped your phone!"
        return {"scenes": scenes}

    converted = prose.convert(DRAMA, reworded, [character("Anudi's Father", "C03")])
    assert converted and converted.by_model == [] and converted.fallbacks == [1, 2, 3]
    assert "Miss! Your phone!" in converted.text and "Excuse me" not in converted.text


def test_fit_seconds():
    assert prose.fit_seconds([20, 30, 10], 60) == [20, 30, 10]
    assert prose.fit_seconds([1, 1, 1], 60) == [20, 20, 20]
    assert prose.fit_seconds([10, 10], None) is None
    assert prose.fit_seconds([1, 100], 6) is None  # would need a scene shorter than the 4 s minimum


def test_the_build_writes_episodes_scenes_and_lines_from_a_prose_document():
    store = FakeStore([doc("pack.pdf", "bible", DRAMA)])
    jobs = FakeJobs(status="running", cursor=1)
    llm = FakeLLM({"prose_scenes": good_cut}, enabled=True)
    result = pipeline.run(build_payload(uuid4()), store, jobs, llm, InMemorySaver(), durable=False)
    assert result["episodes"] == 3 and result["scenes"] == 3 + 2  # ep 1: model's three; eps 2, 3: rules, one each
    assert any("tells its episodes as prose" in t for t in jobs.texts("agent_step"))
    assert any("did not keep every spoken line" in t for t in jobs.texts("warning"))
    assert llm.calls[0]["tier"] == "high" and llm.calls[0]["phase"] == "structure_build.prose"
    lengths = sorted(s["envelope_s"] for s in store.scene_rows.values())
    assert lengths == [10, 20, 30, 60, 60]
    assert sum(len(v) for v in store.line_rows.values()) > 10


def test_without_a_key_the_build_still_makes_scenes():
    store = FakeStore([doc("pack.pdf", "bible", DRAMA)])
    jobs = FakeJobs(status="running", cursor=1)
    result = pipeline.run(build_payload(uuid4()), store, jobs, FakeLLM(enabled=False), InMemorySaver(),
                          durable=False)
    assert result["episodes"] == 3 and result["scenes"] == 3
    assert not jobs.texts("warning") or all("did not keep" not in t for t in jobs.texts("warning"))
