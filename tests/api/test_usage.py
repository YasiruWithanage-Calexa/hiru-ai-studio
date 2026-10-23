from __future__ import annotations

import asyncio

import pytest

from api.config import get_settings
from tests.api.conftest import World


def _record(world: World, input_tokens: int, output_tokens: int) -> None:
    asyncio.run(world.repos.usage.record({"phase": "t", "model": "m", "input_tokens": input_tokens,
                                          "output_tokens": output_tokens}))


@pytest.fixture(autouse=True)
def small_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings().usage, "monthly_token_budget", 1000)


def test_usage_is_a_percentage_only(world: World):
    _record(world, 200, 50)
    r = world.client.get("/v1/usage", headers=world.headers(world.reviewer))
    assert r.status_code == 200
    assert r.json() == {"percent": 25}


def test_usage_is_capped_at_100(world: World):
    _record(world, 5000, 5000)
    r = world.client.get("/v1/usage", headers=world.headers(world.admin))
    assert r.json() == {"percent": 100}


def test_usage_needs_sign_in(world: World):
    assert world.client.get("/v1/usage").status_code == 401
