"""Paid calls of the two-memories lab (plan/2026-11-11 phase 0), under the person's HARD CAP of $1.00 for the whole lab
(set 2026-11-11, instead of the plan's $8).

Rules, all code: a call is refused BEFORE it is sent when the ledger total plus this call's worst case (every input token
uncached, `max_output` spent) would pass the cap; every answer is cached on disk by the hash of its request (the same
request never costs twice); a failed or usage-less call is entered at its worst case. Only this module reads `.env`."""
from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from hiru_ai.core.tokens import tokens_of

LAB_CAP_USD = 1.00
MODEL, EFFORT = "gpt-6.1-sol", "medium"
PRICE = (2.00, 0.10, 10.00)  # $/1M: input, cached input, output (contracts/raphael/money.py)
RUNS = Path(__file__).resolve().parent / "runs"
LEDGER = RUNS / "ledger.csv"
FIELDS = ["time", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "dollars", "status", "hypothesis"]


class CapError(Exception):
    pass


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def worst_case(input_tokens: int, max_output: int) -> float:
    return input_tokens * PRICE[0] / 1e6 + max_output * PRICE[2] / 1e6


def _enter(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def call(slot: str, system: str, user: str, schema: dict[str, Any], *, max_output: int, hypothesis: str) -> str:
    """One structured call: from the cache if the same request was answered, else paid, capped and entered."""
    key = hashlib.sha256(json.dumps([system, user, schema, MODEL, EFFORT], sort_keys=True).encode()).hexdigest()[:24]
    cached = RUNS / "cache" / f"{key}.json"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    tin = tokens_of(system) + tokens_of(user)
    worst = worst_case(tin, max_output)
    if spent() + worst > LAB_CAP_USD + 1e-9:
        raise CapError(f"Refused: ${spent():.4f} spent and this call could cost ${worst:.4f}, which passes the ${LAB_CAP_USD:.2f} cap.")
    from cinematic.run import client  # the only place a client is built; it reads .env

    try:
        resp = client().responses.create(
            model=MODEL, instructions=system, input=user, max_output_tokens=max_output, reasoning={"effort": EFFORT},
            text={"format": {"type": "json_schema", "name": "split", "schema": schema, "strict": True}})
    except Exception as exc:
        _enter({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "slot": slot, "model": MODEL, "effort": EFFORT,
                "dollars": f"{worst:.4f}", "status": f"failed, entered at worst case: {type(exc).__name__}", "hypothesis": hypothesis})
        raise
    u = getattr(resp, "usage", None)
    if u is None:
        dollars, row = worst, {}
    else:
        cached_t = int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0)
        i, o = int(u.input_tokens or 0), int(u.output_tokens or 0)
        dollars = (i - cached_t) * PRICE[0] / 1e6 + cached_t * PRICE[1] / 1e6 + o * PRICE[2] / 1e6
        row = {"input_tokens": i, "cached_tokens": cached_t, "output_tokens": o}
    status = "done" if getattr(resp, "status", "completed") == "completed" else f"cut off ({resp.status})"
    _enter({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "slot": slot, "model": MODEL, "effort": EFFORT,
            "dollars": f"{dollars:.4f}", "status": status, "hypothesis": hypothesis, **row})
    text = str(getattr(resp, "output_text", "") or "")
    if status == "done":
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    else:
        raise CapError(f"The answer was {status}; it was not cached. ${dollars:.4f} entered.")
    return text
