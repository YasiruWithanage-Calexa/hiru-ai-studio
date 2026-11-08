"""The run cap (plan/2026-11-08e §4): $5 of model tokens per scene run, both stages together. Pure arithmetic.

After each model call the run's cost is added to its total; at the cap the run stops (`CapReached`). The last call may
take
it a few cents over. No budget is shown to the model, and nothing here reaches a browser: the cap is seconds of takes
for a
person and dollars for the run only, kept in config and logs (the interface shows no costs, CLAUDE.md).

A model with no price here is refused (`unpriced`): a run never spends against a price it does not know. Prices are per
million tokens, (input, cached input, output); they were read off OpenAI's model pages (gpt-5 family 2026-11-06;
gpt-6.1-sol
2026-11-06, under 272K input). A price change is an edit here, the one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RUN_CAP_USD = 5.00
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-6.1-sol": (2.00, 0.10, 10.00),
    # plan/2026-11-08f: read off developers.openai.com/docs/pricing (Standard tab, short context) on 2026-11-08. The 6.1
    # models also bill cache writes ($1.25 / $2.50 per 1M for a 30 min write, Terra / Sol), which this meter does not
    # count: its total runs a little under the bill.
    "gpt-6.1-terra": (1.00, 0.05, 5.00),
}


class CapReached(Exception):
    """The run's model spend reached the cap: it stops here."""


class Unpriced(Exception):
    """The model has no price in `PRICES`: the run does not start."""


def price_of(model: str) -> tuple[float, float, float]:
    for key, price in PRICES.items():
        if re.fullmatch(re.escape(key) + r"(-\d{4}-\d{2}-\d{2})?", model):
            return price
    raise Unpriced(f"{model} has no price in contracts.raphael.money.PRICES")


def dollars(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    """What one call cost: uncached input + cached input + output (reasoning is billed as output)."""
    inp, cached, out = price_of(model)
    fresh = max(input_tokens - cached_tokens, 0)
    return (fresh * inp + cached_tokens * cached + output_tokens * out) / 1_000_000


@dataclass
class Meter:
    """One scene run's spend against the cap. Both stages share it, so stage 2 gets what stage 1 left."""

    cap_usd: float = RUN_CAP_USD
    spent: float = 0.0
    calls: int = 0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.cap_usd - 1e-9

    def charge(self, model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
        cost = dollars(model, input_tokens, cached_tokens, output_tokens)
        self.spent += cost
        self.calls += 1
        return cost

    def guard(self) -> None:
        if self.exhausted:
            raise CapReached(f"The run reached its ${self.cap_usd:.2f} cap: it stops here.")
