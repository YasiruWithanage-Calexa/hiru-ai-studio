from __future__ import annotations

from tests.api.conftest import World


def test_member_list_is_admin_only(world: World):
    assert world.client.get("/v1/members", headers=world.headers(world.producer)).status_code == 403
    assert len(world.client.get("/v1/members", headers=world.headers(world.admin)).json()) == 7


def test_admin_promotes_and_deactivates(world: World):
    h = world.headers(world.admin)
    r = world.client.patch(f"/v1/members/{world.producer}", json={"app_role": "admin"}, headers=h)
    assert r.json()["app_role"] == "admin"
    r = world.client.patch(f"/v1/members/{world.writer}", json={"active": False}, headers=h)
    assert r.json()["active"] is False


def test_last_admin_cannot_be_removed(world: World):
    h = world.headers(world.admin)
    r = world.client.patch(f"/v1/members/{world.admin}", json={"app_role": "member"}, headers=h)
    assert r.status_code == 409
    r = world.client.patch(f"/v1/members/{world.admin}", json={"active": False}, headers=h)
    assert r.status_code == 409


def test_invite_new_person_sends_email(world: World):
    r = world.client.post("/v1/invitations", headers=world.headers(world.admin), json={
        "email": "New.Person@HiruTV.lk", "production_id": str(world.production),
        "production_role": "director"})
    assert r.status_code == 201 and r.json() == {"email": "new.person@hirutv.lk", "outcome": "invited"}
    assert world.repos.auth_admin.sent == ["new.person@hirutv.lk"]  # type: ignore[attr-defined]
    assert len(world.client.get("/v1/invitations", headers=world.headers(world.admin)).json()) == 1


def test_invite_existing_person_applies_role_directly(world: World):
    r = world.client.post("/v1/invitations", headers=world.headers(world.admin), json={
        "email": "outsider@hirutv.lk", "production_id": str(world.production),
        "production_role": "reviewer"})
    assert r.json()["outcome"] == "added"
    assert world.repos.auth_admin.sent == []  # type: ignore[attr-defined]
    assert world.client.get(f"/v1/productions/{world.production}",
                            headers=world.headers(world.outsider)).status_code == 200


def test_failed_email_leaves_no_invitation(world: World):
    world.repos.auth_admin.fail = True  # type: ignore[attr-defined]
    r = world.client.post("/v1/invitations", headers=world.headers(world.admin),
                          json={"email": "x@hirutv.lk"})
    assert r.status_code == 502
    assert world.repos.invitations.rows == {}  # type: ignore[attr-defined]


def test_invitation_needs_role_with_production(world: World):
    r = world.client.post("/v1/invitations", headers=world.headers(world.admin),
                          json={"email": "x@hirutv.lk", "production_id": str(world.production)})
    assert r.status_code == 422


def test_producer_cannot_invite(world: World):
    r = world.client.post("/v1/invitations", headers=world.headers(world.producer),
                          json={"email": "x@hirutv.lk"})
    assert r.status_code == 403
