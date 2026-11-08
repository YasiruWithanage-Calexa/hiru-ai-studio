"""The traffic log (plan/2026-11-08c phase 0): counts per route and warns on a runaway route or a refetched file."""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from api import traffic
from api.config import get_settings
from api.services import file_cache
from tests.api.fakes import build_fake_repos


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DEBUG_TRAFFIC", "true")
    get_settings.cache_clear()
    from api.main import create_app

    traffic.TRAFFIC.routes.clear()
    with TestClient(create_app(build_fake_repos())) as c:
        yield c
    monkeypatch.setattr(file_cache, "ON_UPSTREAM", None)


def test_calls_are_counted_per_route_not_per_id(client: TestClient) -> None:
    for _ in range(3):
        client.get("/v1/productions/00000000-0000-0000-0000-000000000001/live")  # 401: still a call
    snap = client.get("/debug/traffic").json()
    names = list(snap["routes"])
    assert names == ["GET /v1/productions/{production_id}/live"], names
    assert snap["routes"][names[0]]["calls"] == 3
    assert set(snap["files"]) == {"hits", "misses", "upstream_bytes"}


def test_a_runaway_route_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    t = traffic.Traffic()
    for _ in range(traffic.CALLS_WARN + 1):
        t.note_call("GET /v1/x", db=2, size=10)
    with caplog.at_level(logging.WARNING, logger="api.traffic"):
        lines = t.flush()
    assert "GET /v1/x calls=61 db=122 bytes=610" in lines[0]
    assert any("61 times" in r.message for r in caplog.records)
    assert t.routes == {}


def test_a_file_fetched_three_times_in_an_hour_is_flagged() -> None:
    t = traffic.Traffic()
    assert [t.note_upstream("frames/a.png", now=n) for n in (0, 10, 20)] == [False, False, True]
    assert t.note_upstream("frames/a.png", now=4000) is False  # the hour moved on
