"""Hiru AI Studio API. Run locally: `uvicorn api.main:app --reload`."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import observability, traffic
from api.config import get_settings
from api.deps.auth import warm_jwks
from api.logging_config import configure_logging
from api.observability import RequestLogMiddleware
from api.repositories import Repos
from api.routers import (
    activity,
    ask,
    breakdown,
    build,
    canon,
    costs,
    director,
    documents,
    files,
    handoff,
    internal,
    jobs,
    live,
    looks,
    me,
    members,
    overview,
    page,
    production,
    productions,
    renders,
    sable,
    scene_canon,
    scene_looks,
    scenes,
    search,
    structure,
    usage,
    zora,
)
from api.services import file_cache
from api.workers import sweeper, task_manager

_logger = logging.getLogger(__name__)


def _warn_on_repeat(key: str) -> None:
    observability.note_trace("FILE", key)
    if traffic.TRAFFIC.note_upstream(key):
        _logger.warning("file fetched from Supabase more than %d times in an hour: %s", traffic.UPSTREAM_WARN, key)


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
            await warm_jwks(settings)
        _logger.info("api started environment=%s", settings.environment)
        # Stuck jobs end (plan/2026-11-08c phase 5). Tests inject their own repos and call `sweep` directly.
        sweep_task = asyncio.create_task(sweeper.run_forever(app.state.repos)) if repos is None else None
        flush_task = asyncio.create_task(traffic.flush_forever()) if settings.debug_traffic else None
        yield
        if flush_task is not None:
            flush_task.cancel()
        if sweep_task is not None:
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweep_task

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
        allow_headers=["Authorization", "Content-Type", "Range", "X-Request-ID"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length", "Content-Disposition",
                        "Server-Timing", "X-Request-ID"],
    )
    if settings.debug_traffic and settings.environment in ("local", "test"):
        # Inside RequestLogMiddleware: it opens the per-request database count this reads.
        app.add_middleware(traffic.TrafficMiddleware)
        if settings.debug_traffic_log:
            observability.TRACE_PATH = Path(settings.debug_traffic_log)
            observability.TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_cache.ON_UPSTREAM = _warn_on_repeat
        app.add_api_route("/debug/traffic", lambda: traffic.TRAFFIC.snapshot(), methods=["GET"],
                          include_in_schema=False)
    app.add_middleware(RequestLogMiddleware)

    @app.exception_handler(task_manager.Busy)
    async def busy(_request: Request, exc: task_manager.Busy) -> JSONResponse:
        """plan/2026-11-12c §3.5: no plan is made against a canon that is being refined, and no refine starts while a
        plan or a build runs."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    for module in (me, members, productions, overview, documents, search, build, structure, canon, looks, scene_looks,
                   scene_canon, scenes, production, page, handoff, renders, costs, director, zora, sable, activity,
                   live, breakdown,
                   ask, jobs, usage, files, internal):
        app.include_router(module.router)
    app.include_router(looks.drafts)  # production-wide: /productions/{id}/looks/draft
    return app


app = create_app()
