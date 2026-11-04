"""`hiru-ai review <log>`: the monthly look at how the tools are really used (plan/2026-11-04 §9.4).

Every tool call leaves one log line (`core.telemetry.log_tool_event`: tool, ms, result tokens, error, truncated;
never the arguments or the result, which hold the script). This reads those lines from a log file and says, per
tool, how often it was called, how often it was refused or failed, how often its answer was cut to its budget, and
what it costs a model to read:

    refused / failed often   the guide or the arguments need work: the model keeps calling it wrong
    cut often                its default is too big for what is asked: page it, or narrow the default
    never called             an agent lists a tool it does not need; take it off the list

The targets are the plan's: under 5 % tool errors. A line from anything else in the log is ignored.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

EVENT = re.compile(r"tool=(?P<tool>\S+) ms=(?P<ms>[\d.]+) result_tokens=(?P<tokens>\d+) error=(?P<error>\S+) "
                   r"truncated=(?P<cut>True|False)")
ERROR_TARGET = 0.05  # tool errors per call (plan §1)
CUT_LIMIT = 0.20  # more than this many answers cut: the default is too big


@dataclass
class Usage:
    calls: int = 0
    refused: int = 0
    failed: int = 0
    cut: int = 0
    tokens: list[int] = field(default_factory=list)
    ms: list[float] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return (self.refused + self.failed) / self.calls if self.calls else 0.0

    @property
    def cut_rate(self) -> float:
        return self.cut / self.calls if self.calls else 0.0

    def p95_ms(self) -> float:
        ordered = sorted(self.ms)
        return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0.0


def read(lines: Iterable[str]) -> dict[str, Usage]:
    """Usage per tool from the log's tool lines."""
    out: dict[str, Usage] = defaultdict(Usage)
    for line in lines:
        found = EVENT.search(line)
        if not found:
            continue
        use = out[found["tool"]]
        use.calls += 1
        use.refused += found["error"] == "refused"
        use.failed += found["error"] not in ("-", "refused")
        use.cut += found["cut"] == "True"
        use.tokens.append(int(found["tokens"]))
        use.ms.append(float(found["ms"]))
    return dict(out)


def advice(name: str, use: Usage) -> list[str]:
    notes = []
    if use.error_rate > ERROR_TARGET:
        notes.append(f"{use.error_rate:.0%} of calls fail or are refused (target under {ERROR_TARGET:.0%}): the guide "
                     "or the argument descriptions need work")
    if use.cut_rate > CUT_LIMIT:
        notes.append(f"{use.cut_rate:.0%} of answers are cut to the budget: page it or narrow its default")
    return notes


def report(usage: dict[str, Usage], listed: Iterable[str] = ()) -> str:
    """One line per tool, then what to look at. `listed` = every tool an agent can call (so one never called shows)."""
    lines = [f"{'tool':22s} {'calls':>6s} {'refused':>8s} {'failed':>7s} {'cut':>5s} {'tokens':>7s} {'p95 ms':>7s}"]
    todo: list[str] = []
    for name in sorted({*usage, *listed}):
        use = usage.get(name, Usage())
        mean = sum(use.tokens) // len(use.tokens) if use.tokens else 0
        lines.append(f"{name:22s} {use.calls:6d} {use.refused:8d} {use.failed:7d} {use.cut:5d} {mean:7d} "
                     f"{use.p95_ms():7.0f}")
        if not use.calls:
            todo.append(f"{name}: never called; if an agent lists it, ask whether it needs it")
        todo += [f"{name}: {note}" for note in advice(name, use)]
    total = sum(u.calls for u in usage.values())
    errors = sum(u.refused + u.failed for u in usage.values())
    lines.append(f"\n{total} calls, {errors} errors ({errors / total:.1%})" if total else "\nno tool calls in the log")
    return "\n".join([*lines, *(["", "To look at:", *(f"  {t}" for t in todo)] if todo else [])])
