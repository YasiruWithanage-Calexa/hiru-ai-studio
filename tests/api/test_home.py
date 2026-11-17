"""The documents page in one request (plan/2026-11-13d phase 4, F9): each part equals its own route's answer."""
from __future__ import annotations

from uuid import uuid4

from tests.api.conftest import World


def test_each_part_is_its_own_routes_answer(world: World) -> None:
    pid = world.production
    did = str(uuid4())
    world.repos.documents.rows[did] = {  # type: ignore[attr-defined]
        "id": did, "production_id": str(pid), "filename": "script.fountain", "mime_type": "text/plain",
        "size_bytes": 10, "status": "ready", "detected_role": "script", "confirmed_role": None, "storage_path": "p",
        "created_at": "2026-11-13T10:00:00+00:00", "updated_at": "2026-11-13T10:00:00+00:00"}
    h = world.headers(world.writer)
    home = world.client.get(f"/v1/productions/{pid}/home", headers=h)
    assert home.status_code == 200, home.text
    body = home.json()
    assert body["production"] == world.client.get(f"/v1/productions/{pid}", headers=h).json()
    assert body["access"] == world.client.get(f"/v1/productions/{pid}/access", headers=h).json()
    assert body["documents"] == world.client.get(f"/v1/productions/{pid}/documents", headers=h).json()
    assert body["board"] == world.client.get(f"/v1/productions/{pid}/director-board", headers=h).json()
    assert [d["id"] for d in body["documents"]] == [did]


def test_a_stranger_gets_404(world: World) -> None:
    r = world.client.get(f"/v1/productions/{world.production}/home", headers=world.headers(world.outsider))
    assert r.status_code == 404
