"""What Shot Planner Adam's model calls cost (plan/2026-11-05 Phase 0): a price for a `token_usage` row and a table of
calls per agent and per scene, for the live runner and the spike to print.

    rows = []                                              # the same rows the table holds, kept in memory
    ctx = RunContext(usage_sink=rows.append, usage_detail=True)
    ... run a scene with ctx ...
    print(table(rows))

Costs appear here and in `IMPLEMENTED.md` only: the interface never shows a credit or a cost (CLAUDE.md). The prices are
OpenAI's list prices on the standard tier, per million tokens, as plan/2026-11-05 §1 used them; a model whose name is
not listed is priced as the nearest listed one that its name starts with, else as gpt-5. An output token includes the
hidden reasoning (a row's `reasoning_tokens` says how much), so cost is never read from the visible answer.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# model prefix -> (input, cached input, output), US dollars per million tokens. Longest prefix wins.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5": (1.25, 0.125, 10.00),
}
Row = dict[str, Any]


def prices(model: str) -> tuple[float, float, float]:
    name = model.lower()
    for prefix in sorted(PRICES, key=len, reverse=True):
        if name.startswith(prefix):
            return PRICES[prefix]
    return PRICES["gpt-5"]


def cost(row: Row) -> float:
    """US dollars one `token_usage` row cost."""
    pin, pcached, pout = prices(str(row.get("model") or ""))
    prompt, cached = int(row.get("input_tokens") or 0), int(row.get("cached_input_tokens") or 0)
    return ((max(prompt - cached, 0) * pin + cached * pcached + int(row.get("output_tokens") or 0) * pout) / 1_000_000)


def agent_of(row: Row) -> str:
    """The part that made a call: `adam_take` from `agent:adam_take`, else the row's phase."""
    component = str(row.get("component") or "")
    return component.split(":", 1)[-1] if component else str(row.get("phase") or "?")


def by_agent(rows: list[Row]) -> list[dict[str, Any]]:
    """One line per agent: calls, the average prompt, answer and reasoning, and the cost; the dearest first."""
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        groups[agent_of(r)].append(r)
    out = []
    for agent, mine in groups.items():
        n = len(mine)
        out.append({"agent": agent, "model": str(mine[0].get("model") or ""), "calls": n,
                    "prompt": round(sum(int(r.get("input_tokens") or 0) for r in mine) / n),
                    "cached": round(sum(int(r.get("cached_input_tokens") or 0) for r in mine) / n),
                    "output": round(sum(int(r.get("output_tokens") or 0) for r in mine) / n),
                    "reasoning": round(sum(int(r.get("reasoning_tokens") or 0) for r in mine) / n),
                    "cost": round(sum(cost(r) for r in mine), 4)})
    return sorted(out, key=lambda x: -x["cost"])


def total(rows: list[Row]) -> float:
    return round(sum(cost(r) for r in rows), 4)


def table(rows: list[Row], *, scenes: int = 1) -> str:
    """The calls of a run as a text table, with the cost of the whole and of one scene."""
    lines = [f"{'agent':<24}{'model':<14}{'calls':>6}{'prompt':>9}{'cached':>9}{'answer':>9}{'thought':>9}{'$':>9}"]
    for a in by_agent(rows):
        lines.append(f"{a['agent']:<24}{a['model'][:13]:<14}{a['calls']:>6}{a['prompt']:>9}{a['cached']:>9}"
                     f"{a['output']:>9}{a['reasoning']:>9}{a['cost']:>9.4f}")
    spent = total(rows)
    lines.append(f"{'total':<24}{'':<14}{len(rows):>6}{'':>36}{spent:>9.4f}")
    if scenes > 1:
        lines.append(f"{'per scene':<24}{'':<14}{'':>6}{'':>36}{spent / scenes:>9.4f}")
    return "\n".join(lines)
