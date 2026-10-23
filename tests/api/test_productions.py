from __future__ import annotations

import pytest

from tests.api.conftest import World

NEW = {"title": "Evening Stories", "orientation": "vertical", "kind": "daily"}


def test_admin_sees_all_productions(world: World):
    r = world.client.get("/v1/productions", headers=world.headers(world.admin))
    assert {p["title"] for p in r.json()} == {"Production One", "Production Two"}


def test_member_sees_only_their_production_with_their_role(world: World):
    body = world.client.get("/v1/productions", headers=world.headers(world.writer)).json()
    assert [(p["title"], p["my_role"]) for p in body] == [("Production One", "writer")]


def test_outsider_sees_none(world: World):
    assert world.client.get("/v1/productions", headers=world.headers(world.outsider)).json() == []


def test_only_admin_creates(world: World):
    r = world.client.post("/v1/productions", json=NEW, headers=world.headers(world.admin))
    assert r.status_code == 201
    assert r.json()["orientation"] == "vertical"
    assert world.repos.audit.entries[-1]["action"] == "production.create"  # type: ignore[attr-defined]
    for user in (world.producer, world.director):
        assert world.client.post("/v1/productions", json=NEW,
                                 headers=world.headers(user)).status_code == 403


def test_create_validates_orientation_and_settings(world: World):
    h = world.headers(world.admin)
    assert world.client.post("/v1/productions", json={**NEW, "orientation": "square"},
                             headers=h).status_code == 422
    assert world.client.post("/v1/productions", json={**NEW, "settings": {"fixed_shot_seconds": 10}},
                             headers=h).status_code == 422


def test_non_member_gets_404_not_403(world: World):
    r = world.client.get(f"/v1/productions/{world.other_production}",
                         headers=world.headers(world.producer))
    assert r.status_code == 404


@pytest.mark.parametrize("role", ["producer", "director", "writer", "crew", "reviewer"])
def test_members_can_read(world: World, role: str):
    r = world.client.get(f"/v1/productions/{world.production}",
                         headers=world.headers(getattr(world, role)))
    assert r.status_code == 200


@pytest.mark.parametrize("role", ["producer", "director", "writer", "crew", "reviewer"])
def test_only_admin_changes_settings_or_orientation(world: World, role: str):
    url = f"/v1/productions/{world.production}"
    body = {"orientation": "vertical"}
    assert world.client.patch(url, json=body, headers=world.headers(getattr(world, role))).status_code == 403
    r = world.client.patch(url, json=body, headers=world.headers(world.admin))
    assert r.status_code == 200 and r.json()["orientation"] == "vertical"


def test_access_endpoint_lists_permissions(world: World):
    url = f"/v1/productions/{world.production}/access"
    producer = world.client.get(url, headers=world.headers(world.producer)).json()
    assert producer["role"] == "producer"
    assert "manage_production" not in producer["permissions"]
    assert "approve_scene" in producer["permissions"]
    admin = world.client.get(url, headers=world.headers(world.admin)).json()
    assert admin["role"] is None and "manage_production" in admin["permissions"]


def test_member_management_is_admin_only(world: World):
    url = f"/v1/productions/{world.production}/members/{world.outsider}"
    assert world.client.put(url, json={"role": "writer"},
                            headers=world.headers(world.producer)).status_code == 403
    r = world.client.put(url, json={"role": "writer"}, headers=world.headers(world.admin))
    assert r.status_code == 200
    listed = world.client.get(f"/v1/productions/{world.production}/members",
                              headers=world.headers(world.outsider)).json()
    assert any(m["email"] == "outsider@hirutv.lk" and m["role"] == "writer" for m in listed)
    assert world.client.delete(url, headers=world.headers(world.admin)).status_code == 204
    assert world.client.get(f"/v1/productions/{world.production}",
                            headers=world.headers(world.outsider)).status_code == 404
