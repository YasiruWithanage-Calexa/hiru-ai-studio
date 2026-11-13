"""The turn budget (plan/2026-11-13 §3.8; the person's targets of 2026-11-13: a plain command or a click under $0.001,
any turn at most $0.02). Code, no model.

    b = Budget(cap_usd)
    ctx = b.watch(ctx)                         every usage row of the turn passes through it (and on to the real sink)
    n = b.output_cap(tier, system, user, role, reserve=REPLY_RESERVE)
                                               the output tokens this call may spend: the role's ceiling, lowered to
                                               what the turn can still afford after pricing its input (all of it
                                               uncached); raises OverBudget when it cannot afford MIN_OUT
    b.spent() / b.left()                       priced from the turn's own usage rows (`contracts.costs`, list prices)

An answer the provider cut off at the cap is not used (`CutOff`): the caller reports the author's work as "did not fit
this turn", writes the reply in code, or makes the conductor's answer a clarify.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from contracts import costs
from hiru_ai.core.context import RunContext
from hiru_ai.core.models import resolve
from hiru_ai.core.tokens import tokens_of
from hiru_ai.core.usage import UsageRow

_log = logging.getLogger(__name__)
TURN_CAP_USD = 0.02
REPLY_RESERVE = 0.003  # what the author and a repair leave in the turn for the reply (gpt-5-mini: about $0.002)
MIN_OUT = 400  # a call that cannot afford this many output tokens is not sent
MAX_OUT = {"conductor": 6000, "author": 12000, "reply": 2000}  # each role's ceiling (the lab's)


class OverBudget(Exception):
    """The turn cannot afford this call: it is not sent."""


class CutOff(Exception):
    """The provider stopped the answer at the output cap: it is not used."""


def cut_off(exc: BaseException) -> bool:
    """Was this failure an answer stopped at its output cap (a strict JSON answer that never closed)?"""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return "length" in name or "max_tokens" in text or "max_output_tokens" in text or "length limit" in text


def _price(model: str) -> costs.Price | None:
    return costs.price_for("tokens", {"model": model}, None, costs.LIST_PRICES)


class Budget:
    def __init__(self, cap_usd: float = TURN_CAP_USD) -> None:
        self.cap = cap_usd
        self.rows: list[UsageRow] = []

    def watch(self, ctx: RunContext) -> RunContext:
        """The context with a sink that keeps this turn's rows, then hands each to the run's own sink."""
        inner = ctx.usage_sink

        def sink(row: UsageRow) -> None:
            self.rows.append(dict(row))
            if inner is not None:
                inner(row)

        return replace(ctx, usage_sink=sink)

    def spent(self) -> float:
        tally = costs.Tally()
        for row in self.rows:
            tally.add(costs.tokens_actual(row, costs.LIST_PRICES))
        return tally.micros / costs.MICROS_PER_USD

    def left(self) -> float:
        return self.cap - self.spent()

    def output_cap(self, tier: str, system: str, user: str, role: str, *, reserve: float = 0.0) -> int:
        """The output tokens one call on `tier` may spend now."""
        ceiling = MAX_OUT.get(role, 2000)
        try:
            model = resolve(tier).model
        except Exception:  # a tier that cannot be read is the model layer's error to raise, not the budget's
            return ceiling
        price = _price(model)
        if price is None or not price.output_micros:
            _log.warning("no list price for %s: the turn budget cannot cap this call", model)
            return ceiling
        afford_usd = self.left() - reserve - (tokens_of(system) + tokens_of(user)) * price.input_micros / 1e12
        afford = afford_usd / (price.output_micros / 1e12)
        if afford < MIN_OUT:
            raise OverBudget(f"{role}: ${max(self.left() - reserve, 0):.4f} left in the turn affords "
                             f"{max(afford, 0):.0f} output tokens")
        return int(min(ceiling, afford))


def describe(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, (OverBudget, CutOff)) else type(exc).__name__


__all__: list[Any] = ["MAX_OUT", "MIN_OUT", "REPLY_RESERVE", "TURN_CAP_USD", "Budget", "CutOff", "OverBudget",
                      "cut_off", "describe"]
