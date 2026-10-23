from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from api.workers import task_manager
from tests.api.conftest import World

SECRET = "internal-secret-for-tests"


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda url, payload: calls.append({"url": url, **payload.model_dump(mode="json")}))
    monkeypatch.setenv("API__INTERNAL_SECRET", SECRET)
    from api.config import get_settings

    get_settings.cache_clear()
    return calls


def ready_doc(world: World, role: str = "script", text_path: str | None = "p/d/extracted.txt", status: str = "ready"):
    rows = world.repos.documents.rows  # type: ignore[attr-defined]
    did = str(uuid4())
    rows[did] = {"id": did, "production_id": str(world.production), "filename": f"{role}.txt", "status": status,
                 "detected_role": role, "confirmed_role": None, "text_path": text_path, "sha256": did,
                 "created_at": "2026-10-23T00:00:00+00:00"}
    return did


def start(world: World, user=None):
    return world.client.post(f"/v1/productions/{world.production}/build", headers=world.headers(user or world.director))


def test_build_starts_one_job_through_three_functions(world: World, fired: list[dict]):
    ready_doc(world)
    r = start(world)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["needs_reingest"] == []
    assert len(fired) == 1
    hop = fired[0]
    assert hop["kind"] == "canon_extract" and hop["cursor"] == 0
    assert hop["pipeline"] == ["canon_extract", "structure_build", "script_split"]
    assert hop["state"] == {"build": True} and hop["url"].endswith(":8205/")
    job = world.repos.jobs.rows[body["job_id"]]  # type: ignore[attr-defined]
    assert job["kind"] == "structure_build" and job["request"]["pipeline"][2] == "script_split"


def test_build_needs_ready_documents_and_only_one_at_a_time(world: World, fired: list[dict]):
    assert start(world).status_code == 409
    ready_doc(world)
    other = ready_doc(world, "bible", status="processing")
    assert start(world).status_code == 409  # still reading one
    world.repos.documents.rows[other]["status"] = "ready"  # type: ignore[attr-defined]
    assert start(world).status_code == 202
    assert start(world).status_code == 409  # already running


def test_documents_read_before_text_was_kept_are_listed(world: World, fired: list[dict]):
    ready_doc(world, text_path=None)
    assert start(world).json()["needs_reingest"] == ["script.txt"]


@pytest.mark.parametrize("role,code", [("writer", 403), ("reviewer", 403), ("crew", 403), ("producer", 202)])
def test_who_may_start_a_build(world: World, fired: list[dict], role: str, code: int):
    ready_doc(world)
    assert start(world, getattr(world, role)).status_code == code


def test_outsider_gets_404(world: World, fired: list[dict]):
    assert start(world, world.outsider).status_code == 404


def test_build_view_is_drawn_from_the_events(world: World, fired: list[dict]):
    ready_doc(world)
    job_id = start(world).json()["job_id"]
    jobs = world.repos.jobs  # type: ignore[assignment]
    jobs.rows[job_id]["status"] = "running"
    add = jobs.add_event
    add(job_id, "stage", {"stage": "read", "state": "active"})
    add(job_id, "agent_step", {"text": "Read 3 files."}, "ingestion")
    add(job_id, "stage", {"stage": "read", "state": "done", "text": "3 files"})
    add(job_id, "stage", {"stage": "canon", "state": "active"})
    add(job_id, "agent_step", {"text": "Canon drafted.", "chips": ["4 core characters"]}, "canon_extractor")
    add(job_id, "warning", {"text": "C04: no voice"}, "canon_extractor")
    view = world.client.get(f"/v1/productions/{world.production}/build", headers=world.headers(world.reviewer)).json()
    stages = {s["stage"]: s["state"] for s in view["stages"]}
    assert stages["read"] == "done" and stages["canon"] == "active" and stages["shots"] == "pending"
    agents = {a["agent"]: a["status"] for a in view["agents"]}
    assert agents == {"ingestion": "done", "canon_extractor": "working"}
    assert [m["kind"] for m in view["messages"]] == ["agent", "agent", "warning"]
    canon_msg = view["messages"][1]
    assert canon_msg["chips"] == ["4 core characters"] and canon_msg["agent_label"] == "Canon extractor"
    assert view["status"] == "running" and view["summary"] == {"episodes": 0, "scenes": 0, "shots": 0}


def test_no_build_yet(world: World):
    view = world.client.get(f"/v1/productions/{world.production}/build", headers=world.headers(world.writer)).json()
    assert view["job_id"] is None and all(s["state"] == "pending" for s in view["stages"])


def _waiting_job_with_questions(world: World, n: int = 2) -> tuple[str, list[str]]:
    job_id = str(uuid4())
    world.repos.jobs.rows[job_id] = {  # type: ignore[attr-defined]
        "id": job_id, "kind": "structure_build", "status": "waiting_input", "cursor": 1,
        "production_id": str(world.production), "requested_by": str(world.director),
        "request": {"pipeline": ["canon_extract", "structure_build", "script_split"]}}
    qids = []
    for i in range(n):
        q = world.repos.questions.add(  # type: ignore[attr-defined]
            production_id=str(world.production), job_id=job_id, key=f"loc:{i}", agent="script_architect",
            scope=f"Ep 01 Scene {i + 1}", title="Question", body="Use L03?", allow_text=False, status="open",
            options=[{"value": "L03", "label": "Use L03"}, {"value": "new", "label": "A new location"}],
            answer=None, answered_by=None, answered_at=None)
        qids.append(q["id"])
    return job_id, qids


def answer(world: World, qid: str, body: dict, user=None):
    return world.client.post(f"/v1/productions/{world.production}/questions/{qid}/answer", json=body,
                             headers=world.headers(user or world.writer))


def test_the_last_answer_resumes_the_build(world: World, fired: list[dict]):
    job_id, (q1, q2) = _waiting_job_with_questions(world)
    r = answer(world, q1, {"value": "L03"})
    assert r.status_code == 200 and r.json()["resumed"] is False and fired == []
    r = answer(world, q2, {"value": "new"})
    assert r.json()["resumed"] is True
    assert len(fired) == 1
    hop = fired[0]
    assert hop["kind"] == "structure_build" and hop["cursor"] == 1 and hop["state"]["resume"] is True
    assert world.repos.jobs.rows[job_id]["status"] == "running"  # type: ignore[attr-defined]
    listed = world.client.get(f"/v1/productions/{world.production}/questions?status=answered",
                              headers=world.headers(world.reviewer)).json()
    assert {q["answer"]["value"] for q in listed} == {"L03", "new"}


def test_answers_are_validated(world: World, fired: list[dict]):
    _, (q1, _) = _waiting_job_with_questions(world)
    assert answer(world, q1, {"value": "L99"}).status_code == 422
    assert answer(world, q1, {"text": "the temple"}).status_code == 422  # free text not allowed here
    assert answer(world, q1, {}).status_code == 422
    assert answer(world, q1, {"value": "L03"}).status_code == 200
    assert answer(world, q1, {"value": "L03"}).status_code == 409


@pytest.mark.parametrize("role,code", [("reviewer", 403), ("crew", 403), ("producer", 200)])
def test_who_may_answer(world: World, fired: list[dict], role: str, code: int):
    _, (q1, _) = _waiting_job_with_questions(world)
    assert answer(world, q1, {"value": "L03"}, getattr(world, role)).status_code == code


def test_question_of_another_production_is_404(world: World, fired: list[dict]):
    _, (q1, _) = _waiting_job_with_questions(world)
    r = world.client.post(f"/v1/productions/{world.other_production}/questions/{q1}/answer", json={"value": "L03"},
                          headers=world.headers(world.admin))
    assert r.status_code == 404


def advance(world: World, body: dict, secret: str = SECRET):
    return world.client.post("/internal/pipeline/advance", json=body, headers={"X-Internal-Secret": secret})


def test_courier_sends_the_next_hop_once(world: World, fired: list[dict]):
    ready_doc(world)
    job_id = start(world).json()["job_id"]
    world.repos.jobs.rows[job_id]["status"] = "running"  # type: ignore[attr-defined]
    fired.clear()
    r = advance(world, {"job_id": job_id, "cursor": 0, "state": {"build": True, "previous": {"created": 3}}})
    assert r.status_code == 200 and r.json() == {"advanced": True}
    assert fired[0]["kind"] == "structure_build" and fired[0]["cursor"] == 1
    assert fired[0]["state"]["previous"] == {"created": 3}
    assert fired[0]["actor_user_id"] == str(world.director)
    assert advance(world, {"job_id": job_id, "cursor": 0, "state": {}}).json() == {"advanced": False}
    assert advance(world, {"job_id": job_id, "cursor": 1, "state": {}}).json() == {"advanced": True}
    assert advance(world, {"job_id": job_id, "cursor": 2, "state": {}}).json() == {"advanced": False}  # last hop
    assert len(fired) == 2


def test_courier_requires_the_internal_secret(world: World, fired: list[dict]):
    body = {"job_id": str(uuid4()), "cursor": 0, "state": {}}
    assert advance(world, body, secret="wrong").status_code == 403
    assert world.client.post("/internal/pipeline/advance", json=body).status_code == 403
    assert advance(world, body).status_code == 404


def test_courier_is_closed_when_no_secret_is_configured(world: World, monkeypatch: pytest.MonkeyPatch):
    from api.config import get_settings

    monkeypatch.setenv("API__INTERNAL_SECRET", "")
    get_settings.cache_clear()
    assert advance(world, {"job_id": str(UUID(int=1)), "cursor": 0, "state": {}}, secret="").status_code == 403


def test_courier_can_send_the_same_function_again(world: World, fired: list[dict]):
    ready_doc(world)
    job_id = start(world).json()["job_id"]
    jobs = world.repos.jobs  # type: ignore[assignment]
    jobs.rows[job_id].update(status="running", cursor=2)
    fired.clear()
    r = advance(world, {"job_id": job_id, "cursor": 2, "again": True, "state": {"scene_ids": ["a"]}})
    assert r.json() == {"advanced": True}
    assert fired[0]["kind"] == "script_split" and fired[0]["cursor"] == 3
    assert fired[0]["pipeline"] == ["canon_extract", "structure_build", "script_split", "script_split"]
    assert jobs.rows[job_id]["request"]["pipeline"][-1] == "script_split"
    dup = advance(world, {"job_id": job_id, "cursor": 2, "again": True, "state": {}})
    assert dup.json() == {"advanced": False} and len(fired) == 1
