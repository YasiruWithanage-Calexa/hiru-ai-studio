from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "structure_build"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from structure_build.engine import analyse, pipeline, write  # noqa: E402

from contracts.build import BUILD_PIPELINE  # noqa: E402
from contracts.jobs import DispatchPayload  # noqa: E402
from tests.services.doc_ingest.conftest import CORPUS  # noqa: E402
from tests.services.fakes import FakeJobs, FakeLLM  # noqa: E402

PID = uuid4()
SCRIPT = (CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8")
OUTLINE = (CORPUS / "harbour-lights-outline.txt").read_text(encoding="utf-8")
UNNUMBERED = ("INT. KAMALA'S HOUSE - NIGHT\n\nRAVI\nහරි.\n\nSCENE 2\n\nNimal waits.\n\n"
              "EXT. KALUGALA BEACH - DAY\n\nWaves.\n")


def canon() -> list[dict[str, Any]]:
    rows = [("character", "C01", "Kamala", ["කමලා"]), ("character", "C02", "Nimal", []),
            ("character", "C03", "Sunil", []), ("character", "C04", "Mrs. Perera", []),
            ("location", "L01", "Kamala's house", []), ("location", "L02", "Kalugala harbour breakwater", []),
            ("location", "L03", "Auction shed", [])]
    return [{"id": str(uuid4()), "kind": k, "code": c, "name": n, "aliases": a} for k, c, n, a in rows]


def doc(filename: str, role: str, text: str) -> dict[str, str]:
    return {"id": str(uuid4()), "filename": filename, "role": role, "text": text}


def test_fixture_needs_no_questions_and_links_every_scene_and_line():
    c = canon()
    plan = analyse.analyse([doc("ep01.fountain", "script", SCRIPT), doc("outline.txt", "outline", OUTLINE)], c)
    assert plan["questions"] == []
    structure = analyse.apply_answers(plan, {}, c)
    eps = structure["episodes"]
    assert [(e["number"], e["title"], len(e["scenes"])) for e in eps] == [
        (1, "The Return", 6), (2, "The Buyer", 0), (3, "Storm Season", 0), (4, "The Search", 0)]
    ids = {x["id"] for x in c}
    for scene in eps[0]["scenes"]:
        assert scene["location"]["id"] in ids
        for b in scene["blocks"]:
            if b["kind"] == "dialogue":
                assert b["character"]["id"] in ids
    assert eps[0]["synopsis"].startswith("Nimal comes home")


def test_questions_for_what_only_a_person_knows():
    c = canon()
    no_number = UNNUMBERED
    c.append({"id": str(uuid4()), "kind": "character", "code": "C05", "name": "Ravindu", "aliases": []})
    plan = analyse.analyse([doc("untitled.txt", "script", no_number)], c)
    keys = sorted(q["key"].split(":")[0] for q in plan["questions"])
    assert keys == ["episode", "loc", "noloc", "spk"]
    ep_q = next(q for q in plan["questions"] if q["key"].startswith("episode"))
    assert ep_q["options"][0] == {"value": "1", "label": "Episode 1"} and ep_q["allow_text"]
    loc_q = next(q for q in plan["questions"] if q["key"].startswith("loc:"))
    assert loc_q["options"][0]["value"] == "L02"  # "Kalugala beach" is close to the harbour, not the same


def test_duplicate_episode_scripts_suggest_the_newest():
    old, new = doc("ep1-draft1.fountain", "script", SCRIPT), doc("ep1-draft2.fountain", "script", SCRIPT)
    plan = analyse.analyse([old, new], canon())
    dup = next(q for q in plan["questions"] if q["key"] == "dup:1")
    assert dup["options"][0]["label"] == "ep1-draft2.fountain"
    structure = analyse.apply_answers(plan, analyse.default_answers(plan["questions"]), canon())
    assert structure["episodes"][0]["doc_ids"] == [new["id"]]
    chosen = analyse.apply_answers(plan, {"dup:1": {"value": f"{old['id']}:0"}}, canon())
    assert chosen["episodes"][0]["doc_ids"] == [old["id"]]


def test_answers_are_applied():
    c = canon()
    text = UNNUMBERED
    c.append({"id": str(uuid4()), "kind": "character", "code": "C05", "name": "Ravindu", "aliases": []})
    plan = analyse.analyse([doc("untitled.txt", "script", text)], c)
    keys = {q["key"].split(":")[0]: q["key"] for q in plan["questions"]}
    answers = {keys["episode"]: {"value": None, "text": "Episode 7"}, keys["spk"]: {"value": "C05"},
               keys["noloc"]: {"value": "previous"}, keys["loc"]: {"value": "new"}}
    ep = analyse.apply_answers(plan, answers, c)["episodes"][0]
    assert ep["number"] == 7
    s1, s2, s3 = ep["scenes"]
    ravindu = next(x for x in c if x["code"] == "C05")
    assert s1["blocks"][0]["character"] == {"id": ravindu["id"]}
    assert s2["location"] == s1["location"]
    assert s3["location"] == {"new": "KALUGALA BEACH"}


def test_write_plan_reuses_ids_keeps_approved_and_adds_drafts_to_canon():
    c = canon()
    c = [x for x in c if x["code"] != "C04"]  # Mrs. Perera not in the canon yet
    structure = analyse.apply_answers(analyse.analyse([doc("e.fountain", "script", SCRIPT)], c), {}, c)
    ep_id, approved_id, stale_id = str(uuid4()), str(uuid4()), str(uuid4())
    existing_scenes = [
        {"id": approved_id, "episode_id": ep_id, "number": 2, "status": "approved", "envelope_s": 90,
         "script_version": 3},
        {"id": stale_id, "episode_id": ep_id, "number": 9, "status": "split", "envelope_s": 60, "script_version": 1}]
    p = write.plan(structure, production_id=str(PID), canon=c, existing_episodes=[{"id": ep_id, "number": 1}],
                   existing_scenes=existing_scenes, envelope_s=60, aspect_ratio="16:9", actor=None)
    assert p.episodes[0]["id"] == ep_id and p.kept_approved == 1
    assert approved_id not in p.scene_ids and len(p.scene_ids) == 5
    assert p.delete_scene_ids == [stale_id]
    assert p.new_characters == ["Mrs. Perera"] and p.entities[0][0]["code"] == "C04"
    scene, lines = p.scenes[0]
    assert scene["envelope_s"] == 60 and scene["status"] == "draft"
    dialogue = [b for b in scene["script"] if b["kind"] == "dialogue"]
    assert [b["line_id"] for b in dialogue] == [ln["id"] for ln in lines]
    assert lines[0]["speaker"] == "Nimal" and lines[0]["delivery"] == "quietly" and lines[0]["words"] == 4


class FakeStore:
    def __init__(self, docs: list[dict[str, str]]) -> None:
        self.docs = docs
        self.canon_rows = canon()
        self.episode_rows: dict[str, dict[str, Any]] = {}
        self.scene_rows: dict[str, dict[str, Any]] = {}
        self.line_rows: dict[str, list[dict[str, Any]]] = {}
        self.question_rows: dict[str, dict[str, Any]] = {}

    def production(self, production_id: UUID) -> dict[str, Any] | None:
        return {"id": str(production_id), "orientation": "vertical", "settings": {"default_scene_envelope_s": 45}}

    def documents(self, production_id: UUID) -> list[dict[str, Any]]:
        return [{"id": d["id"], "filename": d["filename"], "confirmed_role": d["role"], "detected_role": None,
                 "text_path": f"x/{d['id']}"} for d in self.docs]

    def text(self, path: str) -> str:
        return next(d["text"] for d in self.docs if d["id"] in path)

    def canon(self, production_id: UUID) -> list[dict[str, Any]]:
        return list(self.canon_rows)

    def create_entity(self, entity: dict[str, Any], version: dict[str, Any]) -> None:
        self.canon_rows.append(entity)

    def episodes(self, production_id: UUID) -> list[dict[str, Any]]:
        return list(self.episode_rows.values())

    def upsert_episodes(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self.episode_rows[r["id"]] = r

    def scenes(self, production_id: UUID) -> list[dict[str, Any]]:
        return list(self.scene_rows.values())

    def write_scene(self, scene: dict[str, Any], lines: list[dict[str, Any]]) -> None:
        self.scene_rows[scene["id"]] = scene
        self.line_rows[scene["id"]] = lines

    def delete_scenes(self, scene_ids: list[str]) -> None:
        for s in scene_ids:
            self.scene_rows.pop(s, None)

    def upsert_questions(self, rows: list[dict[str, Any]]) -> None:
        for r in rows:
            self.question_rows[r["id"]] = r

    def answers(self, job_id: UUID) -> list[dict[str, Any]]:
        return [q for q in self.question_rows.values() if q["job_id"] == str(job_id)]

    def earlier_answers(self, production_id: UUID) -> list[dict[str, Any]]:
        return [q for q in self.question_rows.values() if q["status"] == "answered"]


QUESTIONABLE = "INT. KAMALA'S HOUSE - NIGHT\n\nNIMAL\nහරි.\n\nEXT. KALUGALA BEACH - DAY\n\nWaves.\n"


def build_payload(job_id: UUID, resume: bool = False) -> DispatchPayload:
    return DispatchPayload(job_id=job_id, kind=BUILD_PIPELINE[1], actor_user_id=uuid4(), production_id=PID,
                           pipeline=list(BUILD_PIPELINE), cursor=1,
                           state={"build": True, **({"resume": True} if resume else {})})


def test_a_question_pauses_the_build_and_the_answer_resumes_it():
    store = FakeStore([doc("untitled.txt", "script", QUESTIONABLE)])
    saver = InMemorySaver()  # stands in for Postgres: the same checkpoints across two deliveries
    job_id = uuid4()
    jobs = FakeJobs(status="running", cursor=1)
    first = pipeline.run(build_payload(job_id), store, jobs, FakeLLM(enabled=False), saver, durable=True)
    assert first == {"waiting": 2}
    assert jobs.status == "waiting_input" and store.scene_rows == {}
    assert {q["status"] for q in store.question_rows.values()} == {"open"}
    assert any(e["type"] == "question" for e in jobs.events)

    # A duplicate delivery while waiting does nothing.
    assert pipeline.run(build_payload(job_id), store, jobs, FakeLLM(enabled=False), saver, durable=True) == {
        "skipped": "waiting for answers"}

    for q in store.question_rows.values():
        value = "4" if q["key"].startswith("episode") else "L02"
        q.update(status="answered", answer={"value": value, "text": None})
    jobs.status = "running"  # what the API's resume does
    done = pipeline.run(build_payload(job_id, resume=True), store, jobs, FakeLLM(enabled=False), saver, durable=True)
    assert done["scenes"] == 2 and done["episodes"] == 1
    assert next(iter(store.episode_rows.values()))["number"] == 4
    beach = next(s for s in store.scene_rows.values() if s["number"] == 2)
    l02 = next(c for c in store.canon_rows if c["code"] == "L02")
    assert beach["location_id"] == l02["id"] and beach["envelope_s"] == 45
    assert jobs.advanced[0]["state"]["scene_ids"] and jobs.advanced[0]["state"]["build"]

    # The next build reuses those answers and does not stop.
    again = FakeJobs(status="running", cursor=1)
    result = pipeline.run(build_payload(uuid4()), store, again, FakeLLM(enabled=False), saver, durable=True)
    assert result["scenes"] == 2 and "Reused 2 answers from earlier builds" in again.texts("progress")


def test_without_durable_checkpoints_the_suggested_answers_are_taken_and_recorded():
    store = FakeStore([doc("untitled.txt", "script", QUESTIONABLE)])
    jobs = FakeJobs(status="running", cursor=1)
    result = pipeline.run(build_payload(uuid4()), store, jobs, FakeLLM(enabled=False), InMemorySaver(), durable=False)
    assert result["scenes"] == 2
    assert {q["status"] for q in store.question_rows.values()} == {"defaulted"}
    assert all(q["answer"]["value"] for q in store.question_rows.values())


def test_architect_names_scenes_with_the_model():
    store = FakeStore([doc("ep01.fountain", "script", SCRIPT)])

    def name(system: str, user: str) -> dict[str, Any]:
        assert "<scenes>" in user and "Episode 1 — The Return" in user
        return {"synopsis": "Nimal returns.", "scenes": [{"number": 1, "title": "Nimal comes home"}]}

    llm = FakeLLM({"episode_names": name})
    pipeline.run(build_payload(uuid4()), store, FakeJobs(status="running", cursor=1), llm, InMemorySaver(),
                 durable=True)
    titles = {s["number"]: s["title"] for s in store.scene_rows.values()}
    assert titles[1] == "Nimal comes home"
    assert titles[2] == "Kalugala Harbour, breakwater, morning"  # the model skipped it: rule label kept
    assert next(iter(store.episode_rows.values()))["synopsis"] == "Nimal returns."
    assert llm.calls[0]["tier"] == "ultra"


def test_scenes_can_be_left_out_of_the_build():
    store = FakeStore([doc("ep01.fountain", "script", SCRIPT)])
    store.production = lambda pid: {"id": str(pid), "orientation": "horizontal",  # type: ignore[method-assign]
                                    "settings": {"build": {"scenes": False}}}
    jobs = FakeJobs(status="running", cursor=1)
    pipeline.run(build_payload(uuid4()), store, jobs, FakeLLM(enabled=False), InMemorySaver(), durable=True)
    assert store.scene_rows == {} and jobs.advanced[0]["state"]["scene_ids"] == []


def test_outline_only_production_gets_episodes_and_a_warning():
    store = FakeStore([doc("outline.txt", "outline", OUTLINE)])
    jobs = FakeJobs(status="running", cursor=1)
    result = pipeline.run(build_payload(uuid4()), store, jobs, FakeLLM(enabled=False), InMemorySaver(), durable=True)
    assert result["episodes"] == 4 and result["scenes"] == 0
    assert any("No scripts" in w for w in jobs.texts("warning"))
