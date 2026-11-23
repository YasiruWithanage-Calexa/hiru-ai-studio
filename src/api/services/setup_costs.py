"""Setup costs (plan/2026-11-23b): what a production and each of its episodes cost to set up, apart from scene cost.

The rules are `contracts.cost_parts` (which part a row is, which episode it is charged to, the dated entries); this
file gathers the rows and keeps the answer for a minute. All-time figures: an episode's setup does not reset each
month. Final prices only; provider cost and margins never leave this process.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from api.cache import AsyncTTLCache, clear_after_job
from api.repositories import Repos
from api.services.costs import price_list
from contracts import cost_parts, costs

SETUP_TTL_S = 60.0
_figures: AsyncTTLCache[cost_parts.SetupFigures] = AsyncTTLCache(SETUP_TTL_S)
clear_after_job(_figures)  # finished work moves the figures: a job's end clears them


def clear() -> None:
    _figures.clear()


async def figures(repos: Repos, production_id: UUID) -> cost_parts.SetupFigures:
    async def load() -> cost_parts.SetupFigures:
        price_rows, rows, episodes, scenes, lines = await asyncio.gather(
            repos.costs.prices(), repos.costs.production_usage(production_id), repos.episodes.list(production_id),
            repos.scenes.list_light(production_id), repos.costs.lines_by_scene(production_id))
        prices = price_list(price_rows) or list(costs.SEED_PRICES)
        job_ids = sorted({str(r["job_id"]) for r in rows if r.get("job_id")})
        jobs = {str(j["id"]): j for j in await repos.costs.jobs_of(job_ids)} if job_ids else {}
        return cost_parts.setup_figures(rows, jobs, scenes, episodes, lines, prices)

    found = await _figures.get(str(production_id), load)
    return found if found is not None else cost_parts.SetupFigures(cost_parts.Setup(), {})
