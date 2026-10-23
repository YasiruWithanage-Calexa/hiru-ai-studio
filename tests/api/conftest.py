from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.repositories import Repos
from tests.api.fakes import build_fake_repos

JWT_SECRET = "test-secret-at-least-32-bytes-long-xxxxxxxx"


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("SUPABASE__JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("SUPABASE__SERVICE_ROLE_KEY", "service-role-key-for-tests")
    monkeypatch.setenv("LOCAL_FUNCTIONS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def token_for(user_id: UUID, *, expires_in: int = 3600, secret: str = JWT_SECRET) -> str:
    claims = {"sub": str(user_id), "aud": "authenticated", "role": "authenticated",
              "exp": int(time.time()) + expires_in}
    return jwt.encode(claims, secret, algorithm="HS256")


@dataclass
class World:
    client: TestClient
    repos: Repos
    admin: UUID
    producer: UUID
    director: UUID
    writer: UUID
    crew: UUID
    reviewer: UUID
    outsider: UUID
    production: UUID
    other_production: UUID

    def headers(self, user: UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {token_for(user)}"}


@pytest.fixture
def world() -> Iterator[World]:
    from api.main import create_app

    repos = build_fake_repos()
    p = repos.profiles
    ids = {
        "admin": p.add("admin@hirutv.lk", "Ada Admin", "admin"),  # type: ignore[attr-defined]
        "producer": p.add("producer@hirutv.lk", "Pat Producer"),  # type: ignore[attr-defined]
        "director": p.add("director@hirutv.lk", "Dee Director"),  # type: ignore[attr-defined]
        "writer": p.add("writer@hirutv.lk", "Wes Writer"),  # type: ignore[attr-defined]
        "crew": p.add("crew@hirutv.lk", "Cam Crew"),  # type: ignore[attr-defined]
        "reviewer": p.add("reviewer@hirutv.lk", "Rae Reviewer"),  # type: ignore[attr-defined]
        "outsider": p.add("outsider@hirutv.lk", "Out Sider"),  # type: ignore[attr-defined]
    }
    with TestClient(create_app(repos)) as client:
        import asyncio

        async def seed() -> tuple[UUID, UUID]:
            one = await repos.productions.create({"title": "Production One", "orientation": "horizontal",
                                                  "created_by": str(ids["admin"])})
            two = await repos.productions.create({"title": "Production Two", "orientation": "vertical",
                                                  "created_by": str(ids["admin"])})
            for role in ("producer", "director", "writer", "reviewer"):
                await repos.members.upsert(UUID(one["id"]), ids[role], role, ids["admin"])
            await repos.members.upsert(UUID(one["id"]), ids["crew"], "production", ids["admin"])
            return UUID(one["id"]), UUID(two["id"])

        one, two = asyncio.run(seed())
        yield World(client=client, repos=repos, production=one, other_production=two, **ids)
