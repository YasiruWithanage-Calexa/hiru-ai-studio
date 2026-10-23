from __future__ import annotations

import time
from uuid import uuid4

import jwt

from tests.api.conftest import JWT_SECRET, World, token_for


def test_health_needs_no_auth(world: World):
    assert world.client.get("/healthz").json() == {"status": "ok"}


def test_missing_token_is_401(world: World):
    assert world.client.get("/v1/me").status_code == 401


def test_bad_signature_is_401(world: World):
    bad = token_for(world.admin, secret="another-secret-that-is-also-32-bytes-long")
    assert world.client.get("/v1/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_expired_token_is_401(world: World):
    old = token_for(world.admin, expires_in=-10)
    assert world.client.get("/v1/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_wrong_audience_is_401(world: World):
    claims = {"sub": str(world.admin), "aud": "anon", "exp": int(time.time()) + 60}
    tok = jwt.encode(claims, JWT_SECRET, algorithm="HS256")
    assert world.client.get("/v1/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_alg_none_is_rejected(world: World):
    tok = jwt.encode({"sub": str(world.admin), "aud": "authenticated",
                      "exp": int(time.time()) + 60}, key="", algorithm="none")
    assert world.client.get("/v1/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_valid_token_without_profile_is_403(world: World):
    assert world.client.get("/v1/me", headers=world.headers(uuid4())).status_code == 403


def test_deactivated_user_is_403_immediately(world: World):
    world.repos.profiles.rows[str(world.writer)]["active"] = False  # type: ignore[attr-defined]
    assert world.client.get("/v1/me", headers=world.headers(world.writer)).status_code == 403


def test_me(world: World):
    body = world.client.get("/v1/me", headers=world.headers(world.admin)).json()
    assert body["display_name"] == "Ada Admin"
    assert body["initials"] == "AA"
    assert body["app_role"] == "admin"


def test_update_my_name(world: World):
    r = world.client.patch("/v1/me", json={"display_name": "  Pat P  "},
                           headers=world.headers(world.producer))
    assert r.status_code == 200
    assert r.json()["display_name"] == "Pat P"
