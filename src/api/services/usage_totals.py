"""A month's spending at final prices for Settings → Usage (plan/2026-11-23). The money is `contracts.usage_totals`;
this file gathers the rows and keeps the answer for a minute.

Reads: the price list, the month's `token_usage` summed by the database (`token_usage_totals`, schema v29; before it,
the rows summed here), and the month's video renders. Nothing is stored. Provider cost and margins never leave this
process: the parts go to a DEBUG log only.
"""
from __future__ import annotations

import asyncio
import logging

from api.cache import AsyncTTLCache, clear_after_job
from api.repositories import Repos, Row
from api.services.costs import price_list
from contracts import costs
from contracts import usage_totals as ut

_logger = logging.getLogger(__name__)

USAGE_TTL_S = 60.0
_months: AsyncTTLCache[ut.MonthUsage] = AsyncTTLCache(USAGE_TTL_S)
clear_after_job(_months)  # finished work moves the figure: a job's end clears it


def clear() -> None:
    _months.clear()


async def month_usage(repos: Repos, month: str | None) -> tuple[str, ut.MonthUsage]:
    """("2026-11", the month at final prices). A bad month raises `ValueError` (the router answers 422)."""
    label, since, until = ut.month_bounds(month)

    async def load() -> ut.MonthUsage:
        prices = price_list(await repos.costs.prices()) or list(costs.SEED_PRICES)
        bounds = ut.boundaries(prices, costs.margins())
        threshold = ut.single_long_from(prices)
        groups: list[Row] | None = None
        renders_task = asyncio.create_task(repos.costs.renders_between(since, until))
        if threshold is not None:
            groups = await repos.costs.token_totals(since, until, bounds, sorted(costs.IMAGE_PHASES),
                                                    costs.METERED_PHASE_PREFIXES, threshold)
        if groups and "phase" not in groups[0]:
            # the v29 function (no phase or job): it cannot say a group's purpose, so sum the rows here (until v30)
            _logger.warning("token_usage_totals is the v29 one; summing rows in the API until v30 is applied")
            groups = None
        if groups is None:
            rows = await repos.costs.usage_between(since, until)
            long = ut.long_by_threshold(threshold) if threshold is not None else ut.long_by_price(prices)
            groups = ut.group_rows(rows, bounds, long)
        renders = await renders_task
        job_ids = sorted({str(g["job_id"]) for g in groups if g.get("job_id")})
        jobs = {str(j["id"]): j for j in await repos.costs.jobs_of(job_ids)} if job_ids else {}
        result = ut.price_month(groups, renders, prices, since, bounds, jobs)
        _logger.debug("month usage month=%s groups=%d renders=%d total=%d missing=%s", label, len(groups),
                      len(renders), result.total.total, dict(result.missing))
        return result

    found = await _months.get(label, load)
    return label, found if found is not None else ut.MonthUsage()
