from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest

from api.deps import auth
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


# ── the signing keys survive a network blip ────────────────────────────────────────────────

KEYS = [{"kid": "k1", "kty": "EC"}]
SETTINGS = SimpleNamespace(supabase=SimpleNamespace(url="https://project.example"))


@pytest.fixture
def jwks(monkeypatch: pytest.MonkeyPatch):
    """An empty key cache, a download that can be made to fail, no waiting between attempts."""
    monkeypatch.setattr(auth, "_jwks", {"keys": [], "fetched_at": 0.0})
    monkeypatch.setattr(auth, "_JWKS_BACKOFF", (0.0, 0.0))
    state = SimpleNamespace(fail=False, calls=0)

    async def download(settings):
        state.calls += 1
        if state.fail:
            raise httpx.ConnectError("down")
        return KEYS

    monkeypatch.setattr(auth, "_download_jwks", download)
    return state


def test_the_last_good_keys_keep_serving_when_a_refresh_fails(jwks):
    assert asyncio.run(auth._fetch_jwks(SETTINGS)) == KEYS
    auth._jwks["fetched_at"] -= auth._JWKS_TTL + 1  # the copy is now old
    jwks.fail = True
    assert asyncio.run(auth._fetch_jwks(SETTINGS)) == KEYS
    calls = jwks.calls
    assert asyncio.run(auth._fetch_jwks(SETTINGS)) == KEYS
    assert jwks.calls == calls  # not asked again straight away: the next try waits


def test_no_keys_at_all_and_a_failed_download_is_an_error(jwks):
    jwks.fail = True
    with pytest.raises(httpx.HTTPError):
        asyncio.run(auth._fetch_jwks(SETTINGS))


def test_a_key_id_we_have_never_seen_needs_the_network(jwks):
    asyncio.run(auth._fetch_jwks(SETTINGS))
    auth._jwks["fetched_at"] -= 1  # not "refreshed while we waited", whatever the clock's tick
    jwks.fail = True
    with pytest.raises(httpx.HTTPError):  # the old copy is the one that lacked it: 503, not a stale answer
        asyncio.run(auth._fetch_jwks(SETTINGS, force=True, stale_ok=False))


def test_a_failed_download_is_tried_again_before_giving_up(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth, "_JWKS_BACKOFF", (0.0, 0.0))
    calls = {"n": 0}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise httpx.ConnectError("blip")
            return httpx.Response(200, json={"keys": KEYS}, request=httpx.Request("GET", url))

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kw: Client())
    assert asyncio.run(auth._download_jwks(SETTINGS)) == KEYS and calls["n"] == 3
    calls["n"] = -10  # never succeeds within three attempts
    with pytest.raises(httpx.ConnectError):
        asyncio.run(auth._download_jwks(SETTINGS))
