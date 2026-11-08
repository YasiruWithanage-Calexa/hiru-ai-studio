"""The money rules of the lab, as code (plan/2026-11-08d §5, phase 0; the habits of lab/cinematic/run.py).

Two numbers, both $5.00 and both constants:

  * `RUN_CAP_USD`  the plan's cap: DaVinci works freely, after each model call its cost is added to the run's total, and
                   at the cap the run STOPS (`CapReached`). The last call, or the last parallel group, may take the run a
                   few cents over.
  * `LAB_BUDGET_USD`  the whole lab (phase 0): a call is refused BEFORE it is sent when the ledger total plus every call
                   in flight plus this call's WORST case (input tokens at the input price + `max_output_tokens` at the
                   output price) would pass it. The lab never spends more than the person agreed.

A model with no price in `cinematic.run.PRICES` is refused. A call that fails, or comes back with no usage, is entered at its
worst case. No budget is shown to a model. Model tokens only: Veo generation is separate and is the person's.
"""
from __future__ import annotations

import csv
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cinematic.run import LabError, dollars, listed_price, price_of  # one price table for both labs

RUN_CAP_USD = 5.00
LAB_BUDGET_USD = 5.00
LEDGER_FIELDS = ["time", "run", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens",
                 "reasoning_tokens", "dollars", "status", "hypothesis"]

__all__ = ["LAB_BUDGET_USD", "RUN_CAP_USD", "CapReached", "LabError", "Meter", "Usage", "dollars", "listed_price", "price_of"]


class CapReached(Exception):
    """The run's model spend reached `RUN_CAP_USD`: it stops here."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    status: str = "done"
    reported: bool = True  # False: the provider sent no usage, so the call is entered at its worst case


def worst_case(model: str, input_tokens: int, max_output: int) -> float:
    """Every input token uncached, every output token spent."""
    return dollars(model, input_tokens, 0, max_output)


class Meter:
    """One run's spend against the cap, and the lab's ledger file against the budget. Safe to share between threads."""

    def __init__(self, ledger: Path, run: str, *, run_cap: float = RUN_CAP_USD, lab_budget: float = LAB_BUDGET_USD,
                 hypothesis: str = "") -> None:
        self.ledger, self.run, self.run_cap, self.lab_budget, self.hypothesis = ledger, run, run_cap, lab_budget, hypothesis
        self.spent = 0.0  # this run
        self.reserved = 0.0  # worst cases of the calls in flight
        self.calls = 0
        self._lock = threading.Lock()

    # the ledger
    def rows(self) -> list[dict[str, str]]:
        if not self.ledger.exists():
            return []
        with self.ledger.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def ledger_total(self) -> float:
        return sum(float(r["dollars"] or 0) for r in self.rows())

    def _append(self, row: dict[str, Any]) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.ledger.exists()
        with self.ledger.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
            if fresh:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})

    # the two rules
    @property
    def exhausted(self) -> bool:
        return self.spent >= self.run_cap - 1e-9

    def guard(self, model: str, input_tokens: int, max_output: int) -> float:
        """Reserve the worst case of one call, or refuse: `CapReached` at the run's cap, `LabError` when the lab's budget
        could not hold the call."""
        worst = worst_case(model, input_tokens, max_output)  # raises LabError for an unpriced model
        with self._lock:
            if self.exhausted:
                raise CapReached(f"The run reached its ${self.run_cap:.2f} cap (${self.spent:.2f} spent): it stops here.")
            total = self.ledger_total()
            if total + self.reserved + worst > self.lab_budget + 1e-9:
                raise LabError(f"Refused: ${total:.2f} is spent, ${self.reserved:.2f} is in flight and this call could cost "
                               f"${worst:.2f} more, which passes the lab's ${self.lab_budget:.2f}. Spending more is the "
                               "person's decision (LAB_BUDGET_USD in money.py).")
            self.reserved += worst
        return worst

    def release(self, worst: float) -> None:
        """Give back a reservation whose call was never sent."""
        with self._lock:
            self.reserved = max(self.reserved - worst, 0.0)

    def charge(self, slot: str, model: str, effort: str, usage: Usage | None, worst: float) -> float:
        """Release the reservation and enter what the call cost (its worst case when the provider reported nothing)."""
        if usage is None or not usage.reported:
            spent, status = worst, "no usage reported: worst case"
            row: dict[str, Any] = {}
        else:
            spent = dollars(model, usage.input_tokens, usage.cached_tokens, usage.output_tokens)
            status = usage.status
            row = {"input_tokens": usage.input_tokens, "cached_tokens": usage.cached_tokens,
                   "output_tokens": usage.output_tokens, "reasoning_tokens": usage.reasoning_tokens}
        with self._lock:
            self.reserved = max(self.reserved - worst, 0.0)
            self.spent += spent
            self.calls += 1
            self._append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": self.run, "slot": slot, "model": model,
                          "effort": effort, "dollars": f"{spent:.4f}", "status": status,
                          "hypothesis": self.hypothesis.replace("\n", " "), **row})
        return spent

    def fail(self, slot: str, model: str, effort: str, worst: float, why: str) -> None:
        """A call that failed may still have been billed: it is entered at its worst case."""
        with self._lock:
            self.reserved = max(self.reserved - worst, 0.0)
            self.spent += worst
            self.calls += 1
            self._append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": self.run, "slot": slot, "model": model,
                          "effort": effort, "dollars": f"{worst:.4f}", "status": f"failed at worst case ({why})",
                          "hypothesis": self.hypothesis.replace("\n", " ")})
