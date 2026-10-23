"""Hiru AI Studio API. Run locally: `uvicorn api.main:app --reload`."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.logging_config import configure_logging
from api.repositories import Repos
from api.routers import files, jobs, me, members, productions

_logger = logging.getLogger(__name__)


def create_app(repos: Repos | None = None) -> FastAPI:
    """`repos` is injected by tests; production builds the Supabase-backed set at startup."""
    settings = get_settings()
    configure_logging(json_output=settings.environment in ("staging", "prod"))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if repos is not None:
            app.state.repos = repos
        else:
            from api.repositories.supabase import build_supabase_repos

            key = settings.supabase.service_role_key.get_secret_value()
            if not key:
                raise RuntimeError("SUPABASE__SERVICE_ROLE_KEY is not set")
            app.state.repos = await build_supabase_repos(settings.supabase.url, key)
        _logger.info("api started environment=%s", settings.environment)
        yield

    app = FastAPI(
        title="Hiru AI Studio API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.environment == "prod" else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for module in (me, members, productions, jobs, files):
        app.include_router(module.router)
    return app


app = create_app()
