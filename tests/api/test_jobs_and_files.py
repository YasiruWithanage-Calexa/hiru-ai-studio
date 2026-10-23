from __future__ import annotations

from uuid import uuid4

import pytest

from api.services import media_links
from api.workers import task_manager
from tests.api.conftest import World


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(task_manager, "_fire_local",
                        lambda url, payload: calls.append({"url": url, **payload.model_dump(mode="json")}))
    return calls


def test_echo_dispatch_creates_job_then_fires(world: World, fired: list[dict]):
    r = world.client.post("/v1/jobs/echo", json={"message": "hello"}, headers=world.headers(world.admin))
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert fired[0]["url"] == "http://localhost:8201/"
    assert fired[0]["job_id"] == job_id and fired[0]["state"] == {"message": "hello"}
    job = world.client.get(f"/v1/jobs/{job_id}", headers=world.headers(world.admin)).json()
    assert job["status"] == "pending" and job["kind"] == "echo"


def test_echo_is_admin_only(world: World, fired: list[dict]):
    assert world.client.post("/v1/jobs/echo", json={}, headers=world.headers(world.producer)).status_code == 403
    assert fired == []


def test_failed_dispatch_marks_job_failed(world: World, monkeypatch: pytest.MonkeyPatch):
    def boom(url, payload):  # type: ignore[no-untyped-def]
        raise RuntimeError("queue down")

    monkeypatch.setattr(task_manager, "_fire_local", boom)
    with pytest.raises(RuntimeError):
        world.client.post("/v1/jobs/echo", json={}, headers=world.headers(world.admin))
    (job,) = world.repos.jobs.rows.values()  # type: ignore[attr-defined]
    assert job["status"] == "failed"


def test_job_visibility_follows_production(world: World):
    jobs = world.repos.jobs
    mine = str(uuid4())
    theirs = str(uuid4())
    jobs.rows[mine] = {"id": mine, "kind": "echo", "status": "done",  # type: ignore[attr-defined]
                       "production_id": str(world.production), "requested_by": str(world.admin),
                       "created_at": "2026-10-23T00:00:00Z", "updated_at": "2026-10-23T00:00:00Z"}
    jobs.rows[theirs] = {**jobs.rows[mine], "id": theirs,  # type: ignore[attr-defined]
                         "production_id": str(world.other_production)}
    jobs.event_rows += [{"job_id": mine, "seq": 1, "type": "status", "payload": {}},  # type: ignore[attr-defined]
                        {"job_id": mine, "seq": 2, "type": "progress", "payload": {"n": 1}}]
    h = world.headers(world.reviewer)
    assert world.client.get(f"/v1/jobs/{mine}", headers=h).status_code == 200
    assert world.client.get(f"/v1/jobs/{theirs}", headers=h).status_code == 404
    events = world.client.get(f"/v1/jobs/{mine}/events?after=1", headers=h).json()
    assert [e["seq"] for e in events] == [2]


def test_file_ticket_round_trip_and_opacity():
    t = media_links.ticket("frames", "prod/shot-1/frame-1.png")
    assert "frames" not in t and "shot-1" not in t  # encrypted, not just encoded
    assert media_links.open_ticket(t) == {"bucket": "frames", "path": "prod/shot-1/frame-1.png"}


def test_file_ticket_rejects_tampering_and_expiry():
    t = media_links.ticket("frames", "a.png")
    tampered = t[:-2] + ("AA" if not t.endswith("AA") else "BB")
    assert media_links.open_ticket(tampered) is None
    assert media_links.open_ticket(media_links.ticket("frames", "a.png", seconds=-1)) is None
    assert media_links.open_ticket("garbage") is None


def test_bad_file_ticket_is_404(world: World):
    assert world.client.get("/files/not-a-ticket").status_code == 404
