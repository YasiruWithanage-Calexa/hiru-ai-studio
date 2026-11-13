"""The agents' answer shapes and the backends that answer them (plan/2026-11-12d phase 0).

    Paid(run)           real calls: the lab cap is checked BEFORE every call at its worst case, every answer is cached by
                        the hash of its request (the same request never costs twice), every call goes in runs/ledger.csv
    Rehearsal(script)   no model: canned answers, to run the whole turn offline

THE TURN BUDGET (run 4, the person: "a small request under $0.001, at most $0.02"): `ask(..., budget=$left)` caps the
call's output at what the turn can still afford (input priced first, all of it uncached); a call that cannot afford
`MIN_OUT` tokens is not sent (`OverBudget`), and one the provider cuts off at the cap raises `CutOff`. Calls on a `_b`
role are the second voice written only to compare: they are never counted against the turn.

Models (run 4): conductor gpt-5-nano low; author gpt-6.1-terra low; the reply on a turn the author did not work on
(small) gpt-5-nano minimal, on one it did (big) gpt-6.1-terra low; `_b` roles are the voices compared beside them.
Runs 1-3 used conductor gpt-5-mini low, author gpt-6.1-sol low, reply gpt-5-mini then gpt-5 (RESULTS.md).
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from contracts import safe_depiction
from hiru_ai.core.tokens import tokens_of

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
LEDGER = RUNS / "ledger.csv"
LAB_CAP_USD = 2.00
TURN_CAP_USD = 0.02
MIN_OUT = 400  # a call that cannot afford this many output tokens is not sent
PRICES = {  # $/1M: input, cached input, output (gpt-6.1 as contracts/raphael/money.py)
    "gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00),
    "gpt-6.1-terra": (1.00, 0.05, 5.00), "gpt-6.1-sol": (2.00, 0.10, 10.00)}
# Run 4: gpt-5-nano misread 5 of 7 messages as the conductor and wrote unreliable replies, so run 5 puts gpt-5-mini
# back at minimal effort on both. A small reply has no second voice now; a big one is compared with gpt-5.
MODELS = {
    "conductor": ("gpt-5-mini", "minimal", 6000),
    "author": ("gpt-6.1-terra", "low", 12000),
    "reply_small": ("gpt-5-mini", "minimal", 1500),
    # run 5: terra's replies were dry and gpt-5's did not fit beside the author in $0.02, so run 6 writes every reply
    # with gpt-5-mini at minimal effort (natural in run 5's small turns, about $0.001-0.002)
    "reply_big": ("gpt-5-mini", "minimal", 2000),
}
COMPARE_REPLIES = True  # write the `_b` voice beside the reply where one is configured (not counted against the turn)
FIELDS = ["time", "run", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "dollars", "status"]

Row = dict[str, Any]
_S = {"type": ["string", "null"]}
_I = {"type": ["integer", "null"]}
_A = {"type": ["array", "null"], "items": {"type": "string"}}
OP_FIELDS = {"op": None, "shot": _S, "field": _S, "value": _S, "take_s": _I, "role": _S, "priority": _S, "after": _S,
             "first_block": _I, "last_block": _I, "who": _A, "what": _S, "at_block": _I, "to_shot": _S, "line": _S}
OP_NAMES = ("set", "retime", "sound", "role", "insert", "remove", "split", "merge", "move", "line")
KINDS = ("picture", "camera", "timing", "sound", "light", "order")


class CapError(Exception):
    """The lab's cap: the run stops."""


class OverBudget(Exception):
    """The turn cannot afford this call: it is not sent."""


class CutOff(Exception):
    """The provider stopped the answer at the output cap: it is not used."""


def prompt(name: str) -> str:
    text = (HERE / "prompts" / f"{name}.md").read_text(encoding="utf-8").strip()
    return text.replace("{SAFE}", safe_depiction.PROMPT_LINE)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def op_schema() -> dict[str, Any]:
    return _obj({k: ({"type": "string", "enum": list(OP_NAMES)} if v is None else v) for k, v in OP_FIELDS.items()})


def conductor_schema() -> dict[str, Any]:
    task = _obj({"writes": {"type": "array", "items": {"type": "string", "enum": list(KINDS)}},
                 "shots": {"type": "array", "items": {"type": "integer"}}, "instruction": {"type": "string"}})
    cannot = {"anyOf": [{"type": "null"}, _obj({"reason": {"type": "string"}, "route": {"type": "string"}})]}
    return _obj({"lane": {"type": "string", "enum": ["chat", "clarify", "edit", "craft", "options", "cannot"]},
                 "confidence": {"type": "number"}, "ops": {"type": "array", "items": op_schema()},
                 "tasks": {"type": "array", "items": task}, "variants": {"type": "integer"}, "cannot": cannot,
                 "memory": {"type": "string"}})


def author_schema() -> dict[str, Any]:
    variant = _obj({"label": {"type": "string"}, "ops": {"type": "array", "items": op_schema()}})
    return _obj({"notes": {"type": "string"}, "ops": {"type": "array", "items": op_schema()},
                 "asks": {"type": "array", "items": {"type": "string"}}, "variants": {"type": "array", "items": variant}})


def clean_op(raw: Row) -> Row:
    """A flat answer object → an operation: nulls and empty lists out."""
    return {k: v for k, v in raw.items() if v is not None and v != []}


def counted(call: Row) -> bool:
    """A call counted against the turn: every call but a second voice written only to compare."""
    return not str(call.get("role", "")).endswith("_b")


def output_cap(role: str, system: str, user: str, budget: float | None, models: dict[str, Any] | None = None) -> int:
    """The output tokens this call may spend: the role's cap, lowered to what the turn can still afford."""
    model, _, max_out = (models or MODELS)[role]
    price = PRICES[model]
    if budget is None:
        return int(max_out)
    afford = (budget - (tokens_of(system) + tokens_of(user)) * price[0] / 1e6) / price[2] * 1e6
    if afford < MIN_OUT:
        raise OverBudget(f"{role}: ${budget:.4f} left in the turn affords {max(afford, 0):.0f} output tokens")
    return int(min(max_out, afford))


# ── backends ───────────────────────────────────────────────────────────────────────────────────────────────────────


class Paid:
    def __init__(self, run: str, models: dict[str, Any] | None = None) -> None:
        self.run, self.calls, self.spent_here = run, [], 0.0
        self.models = dict(models or MODELS)

    @staticmethod
    def spent() -> float:
        if not LEDGER.exists():
            return 0.0
        with LEDGER.open(encoding="utf-8", newline="") as f:
            return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))

    def ask(self, role: str, slot: str, system: str, user: str, schema: dict[str, Any] | None,
            budget: float | None = None) -> tuple[str, float]:
        model, effort, _ = self.models[role]
        price = PRICES[model]
        key = hashlib.sha256(json.dumps([system, user, schema, model, effort], sort_keys=True).encode()).hexdigest()[:24]
        cached = RUNS / "cache" / f"{key}.json"
        if cached.exists():
            self.calls.append({"slot": slot, "role": role, "model": model, "effort": effort, "dollars": 0.0,
                               "cached": True})
            return cached.read_text(encoding="utf-8"), 0.0
        max_out = output_cap(role, system, user, budget, self.models)
        worst = (tokens_of(system) + tokens_of(user)) * price[0] / 1e6 + max_out * price[2] / 1e6
        if self.spent() + worst > LAB_CAP_USD + 1e-9:
            raise CapError(f"Refused before sending: ${self.spent():.4f} spent, this call could cost ${worst:.4f}, "
                           f"the lab cap is ${LAB_CAP_USD:.2f}.")
        from cinematic.run import client  # the only place a client is built; it reads .env

        base = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": self.run, "slot": slot, "model": model,
                "effort": effort}
        args: Row = {"model": model, "instructions": system, "input": user, "max_output_tokens": max_out,
                     "reasoning": {"effort": effort}}
        if schema is not None:
            args["text"] = {"format": {"type": "json_schema", "name": role, "schema": schema, "strict": True}}
        started = time.time()
        try:
            resp = client().responses.create(**args)
        except Exception as exc:
            self._enter({**base, "dollars": f"{worst:.4f}", "status": f"failed: {type(exc).__name__}"})
            self.calls.append({"slot": slot, "role": role, "model": model, "effort": effort, "dollars": worst,
                               "failed": True})
            raise
        u = getattr(resp, "usage", None)
        if u is None:
            dollars, usage = worst, {}
        else:
            c = int(getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0)
            i, o = int(u.input_tokens or 0), int(u.output_tokens or 0)
            dollars = (i - c) * price[0] / 1e6 + c * price[1] / 1e6 + o * price[2] / 1e6
            usage = {"input_tokens": i, "cached_tokens": c, "output_tokens": o}
        status = "done" if getattr(resp, "status", "completed") == "completed" else f"cut off ({resp.status})"
        self._enter({**base, "dollars": f"{dollars:.4f}", "status": status, **usage})
        self.spent_here += dollars
        self.calls.append({"slot": slot, "role": role, "model": model, "effort": effort, "dollars": round(dollars, 5),
                           "seconds": round(time.time() - started, 1), "max_out": max_out, **usage})
        print(f"    {slot}: {model} {effort} {status} {time.time() - started:.0f} s ${dollars:.5f}", flush=True)
        text = str(getattr(resp, "output_text", "") or "")
        if status != "done":
            raise CutOff(f"{slot} was {status} at {max_out} output tokens; ${dollars:.4f} entered, not used.")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
        return text, dollars

    def _enter(self, row: Row) -> None:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        fresh = not LEDGER.exists()
        with LEDGER.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if fresh:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in FIELDS})


class Rehearsal:
    """Canned answers: `script[slot]` is the answer (a dict for JSON, a str for the reply). A slot with no answer gets
    the plain one (conductor: clarify; author: nothing; reply: the facts in one line)."""

    def __init__(self, script: dict[str, Any]) -> None:
        self.script, self.calls, self.spent_here = script, [], 0.0
        self.models = dict(MODELS)

    def ask(self, role: str, slot: str, system: str, user: str, schema: dict[str, Any] | None,
            budget: float | None = None) -> tuple[str, float]:
        self.calls.append({"slot": slot, "role": role, "model": "rehearsal", "dollars": 0.0})
        if slot in self.script:
            ans = self.script[slot]
            return (ans if isinstance(ans, str) else json.dumps(ans)), 0.0
        if role == "conductor":
            return json.dumps({"lane": "clarify", "confidence": 0.2, "ops": [], "tasks": [], "variants": 0,
                               "cannot": None, "memory": ""}), 0.0
        if role == "author":
            return json.dumps({"notes": "", "ops": [], "asks": [], "variants": []}), 0.0
        facts = user.rsplit("WHAT HAPPENED THIS TURN", 1)[-1].split(":\n", 1)[-1]
        return "(rehearsal reply) " + facts.replace("</turn>", "").strip().replace("\n", " ")[:400], 0.0


def worst_case_table() -> list[tuple[str, str, str, float]]:
    """Per role: model, effort, and the worst case of one call on a 4k-token input at the role's output cap."""
    out = []
    for role, (model, effort, max_out) in MODELS.items():
        p = PRICES[model]
        out.append((role, model, effort, 4000 * p[0] / 1e6 + max_out * p[2] / 1e6))
    return out
