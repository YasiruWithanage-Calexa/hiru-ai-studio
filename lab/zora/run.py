"""Zora's lab (plan/2026-11-06e Phase 3): dry run, offline run, paid run, budget, cache, ledger, blind page.

    python lab/zora/run.py dry [--case ID] [--arm A|B]     the exact prompts of one case and what a run could cost (free)
    python lab/zora/run.py cost [--split tune] [--k 1]     the worst case and the likely price of a whole run (free)
    python lab/zora/run.py offline                         every case on recorded answers (lab/zora/answers): free
    python lab/zora/run.py paid --yes --arm A --split tune --hypothesis "…"     real calls (costs money)
    python lab/zora/run.py ledger                          every paid call so far and the total (free)
    python lab/zora/run.py compare --run DIR_A --run DIR_B the blind page: which end plan would you shoot? (free)

Run everything but `paid` with `OPENAI__API_KEY=` blank. The money rules are code (the cinematic lab's, copied):

  * `BUDGET_USD = 3.00` (D10). A call is refused when the ledger total plus its WORST case (input tokens at the input
    price + `max_output_tokens` at the output price) would pass it. A model with no price in `PRICES` is refused.
  * A failed call is entered at its worst case. The same request (model, effort, system, user, schema) is answered
    from the cache for free: never pay twice.
  * After the first paid run a run needs `--hypothesis`: one change per paid run. Stop when the held-out cases pass at
    k=3 (`--k 3`), or when the budget says stop.
  * The author arms run on the case's RECORDED conductor answer, so A and B differ only by the author side; the
    conductor is run live and scored on its own (lane, ops, declared effects).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # started as a script: put the repo's import roots on the path
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_ROOT / "lab"), str(_ROOT / "src" / "libs"), str(_ROOT / "src"), str(_ROOT)]

from contracts.zora import effects as E
from hiru_ai.core.tokens import tokens_of
from contracts.zora import wire as schema
from zora import turn

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
RUNS, ANSWERS, CACHE = LAB / "runs", LAB / "answers", LAB / "runs" / "cache"
LEDGER = RUNS / "ledger.csv"
CASES = ROOT / "tests" / "eval" / "zora" / "cases.json"

BUDGET_USD = 3.00  # D10: the whole lab. Raising it is a code change the person asks for.
# role → (model, effort, max_output_tokens). The author is the planner's model at a lower effort (D7); the conductor
# and arm B's seats are the `medium` tier.
MODELS: dict[str, tuple[str, str, int]] = {"conductor": ("gpt-5-mini", "low", 6_000),
                                           "author": ("gpt-6.1-sol", "low", 12_000),
                                           "seat": ("gpt-5-mini", "medium", 8_000)}
EXPECTED_OUTPUT = {"conductor": 1_500, "author": 4_000, "seat": 2_500}  # the likely price; the worst case is enforced
# model → (input, cached input, output) US dollars per million tokens, as read by the planner's spike and the
# cinematic lab off OpenAI's pricing pages (2026-11-06). An unlisted model is refused.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00),
    "gpt-6.1-sol": (2.00, 0.10, 10.00)}
LEDGER_FIELDS = ["time", "run", "case", "role", "model", "effort", "input_tokens", "cached_tokens", "output_tokens",
                 "dollars", "status", "hypothesis"]


class LabError(Exception):
    pass


def cases(split: str = "", only: str = "") -> list[dict[str, Any]]:
    out = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    return [c for c in out if (not split or c["split"] == split) and (not only or c["id"] == only)]


def price_of(model: str) -> tuple[float, float, float]:
    for key, price in PRICES.items():
        if re.fullmatch(re.escape(key) + r"(-\d{4}-\d{2}-\d{2})?", model.lower()):
            return price
    raise LabError(f"The model {model} has no price in PRICES (run.py): read it off OpenAI's pricing page first.")


def dollars(model: str, inp: int, cached: int, out: int) -> float:
    pin, pcached, pout = price_of(model)
    return (max(inp - cached, 0) * pin + cached * pcached + out * pout) / 1_000_000


def read_ledger() -> list[dict[str, str]]:
    if not LEDGER.exists():
        return []
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ledger_total() -> float:
    return sum(float(r["dollars"] or 0) for r in read_ledger())


def add_to_ledger(row: dict[str, Any]) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LEDGER_FIELDS})


def role_of(role: str) -> str:
    return "seat" if role.startswith("seat:") else role


def key_of(role: str, system: str, user: str, schema_: dict[str, Any]) -> str:
    model, effort, cap = MODELS[role_of(role)]
    body = json.dumps([model, effort, cap, system, user, schema_], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:24]


def worst(role: str, system: str, user: str) -> float:
    model, _, cap = MODELS[role_of(role)]
    return dollars(model, int(tokens_of(system + user) * 1.15) + 50, 0, cap)


# ── calls ──────────────────────────────────────────────────────────────────────────────────────────


class Recorded:
    """Answers from `lab/zora/answers/<case>.json` ({role: answer or [answers]}); an empty answer when there is none.
    Free: the offline run and the tests."""

    def __init__(self, case: str) -> None:
        path = ANSWERS / f"{case}.json"
        self.answers: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.used: dict[str, int] = {}

    def __call__(self, role: str, system: str, user: str, schema_: dict[str, Any]) -> dict[str, Any]:
        got = self.answers.get(role)
        n = self.used.get(role, 0)
        self.used[role] = n + 1
        if isinstance(got, list):
            got = got[n] if n < len(got) else None
        return dict(got or {"notes": "", "ops": [], "asks": [], "variants": []})


class Paid:
    """Real calls, each guarded by the budget and answered from the cache when the same request was paid before."""

    def __init__(self, run: str, case: str, hypothesis: str) -> None:
        self.run, self.case, self.hypothesis = run, case, hypothesis
        self._client: Any = None

    def client(self) -> Any:
        if self._client is None:
            from hiru_ai.core.llm import openai_client
            from hiru_ai.core.settings import get_settings
            load_env()
            get_settings.cache_clear()
            self._client = openai_client(timeout_s=900.0, retries=0)
        return self._client

    def __call__(self, role: str, system: str, user: str, schema_: dict[str, Any]) -> dict[str, Any]:
        key = key_of(role, system, user, schema_)
        hit = CACHE / f"{key}.json"
        if hit.exists():
            return dict(json.loads(hit.read_text(encoding="utf-8")))
        model, effort, cap = MODELS[role_of(role)]
        cost = worst(role, system, user)
        spent = ledger_total()
        if spent + cost > BUDGET_USD + 1e-9:
            raise LabError(f"Refused: ${spent:.2f} is spent and this call could cost ${cost:.2f} more, which passes the "
                           f"${BUDGET_USD:.2f} limit. Spending more is the person's decision.")
        base = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": self.run, "case": self.case, "role": role,
                "model": model, "effort": effort, "hypothesis": self.hypothesis.replace("\n", " ")}
        try:
            resp = self.client().responses.create(
                model=model, instructions=system, input=user, max_output_tokens=cap, reasoning={"effort": effort},
                text={"format": {"type": "json_schema", "name": schema_["title"], "schema": schema_, "strict": True}})
        except Exception as exc:
            add_to_ledger({**base, "dollars": f"{cost:.4f}", "status": f"failed at worst case ({type(exc).__name__})"})
            raise LabError(f"the {role} call failed ({type(exc).__name__}: {exc}); ${cost:.2f} entered") from exc
        usage = getattr(resp, "usage", None)
        if usage is None:
            add_to_ledger({**base, "dollars": f"{cost:.4f}", "status": "no usage: worst case"})
        else:
            cached = int(getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0)
            paid = dollars(model, int(usage.input_tokens or 0), cached, int(usage.output_tokens or 0))
            add_to_ledger({**base, "input_tokens": usage.input_tokens, "cached_tokens": cached,
                           "output_tokens": usage.output_tokens, "dollars": f"{paid:.4f}",
                           "status": "done" if getattr(resp, "status", "completed") == "completed" else "cut off"})
        try:
            answer = json.loads(str(getattr(resp, "output_text", "") or "{}"))
        except ValueError:
            answer = {}
        CACHE.mkdir(parents=True, exist_ok=True)
        hit.write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
        return dict(answer)


def load_env(path: Path = ROOT / ".env") -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ── the conductor, scored on its own ───────────────────────────────────────────────────────────────


def score_conductor(case: dict[str, Any], answer: dict[str, Any]) -> dict[str, bool]:
    want = case.get("conduct") or case["turns"][-1]["conduct"]
    ops = [schema.to_op(o) for o in answer.get("ops") or []]
    declared = {E.normalize_effect(e) for t in answer.get("tasks") or [] for e in t.get("writes") or []}
    wanted = {e for t in want["tasks"] for e in t["writes"]}
    return {"lane": answer.get("lane") == want["lane"],
            "ops": sorted(o.get("op", "") for o in ops) == sorted(o["op"] for o in want["ops"]),
            "declared": wanted <= declared if wanted else not declared - {""}}


# ── commands ───────────────────────────────────────────────────────────────────────────────────────


def cmd_dry(args: argparse.Namespace) -> int:
    case = cases(only=args.case)[0]
    doc = turn.fixture(case["scene"])
    message = case.get("message") or case["turns"][-1]["person"]
    system, user = turn.conductor_system(), turn.conductor_message(doc, message, [])
    print(f"=== conductor: {len(system)} + {len(user)} characters, worst ${worst('conductor', system, user):.3f}")
    print(user[-1500:])
    seen: dict[str, str] = {}

    def capture(role: str, system_: str, user_: str, schema_: dict[str, Any]) -> dict[str, Any]:
        seen[role] = user_
        print(f"=== {role}: {len(system_)} + {len(user_)} characters, worst ${worst(role, system_, user_):.3f}")
        return {"notes": "", "ops": [], "asks": [], "variants": []}

    turn.run_turn(case, capture, arm=args.arm)
    if args.show and seen:
        print(next(iter(seen.values())))
    print(f"spent so far ${ledger_total():.2f} of ${BUDGET_USD:.2f}")
    return 0


def cmd_cost(args: argparse.Namespace) -> int:
    total_worst = total_likely = 0.0
    for case in cases(args.split):
        doc = turn.fixture(case["scene"])
        message = case.get("message") or case["turns"][-1]["person"]
        system, user = turn.conductor_system(), turn.conductor_message(doc, message, [])
        roles = [("conductor", system, user)]

        def capture(role: str, system_: str, user_: str, schema_: dict[str, Any],
                    roles: list[tuple[str, str, str]] = roles) -> dict[str, Any]:
            roles.append((role, system_, user_))
            return {"notes": "", "ops": [], "asks": [], "variants": []}

        for arm in args.arms:
            turn.run_turn(case, capture, arm=arm)
        for role, s, u in roles:
            model = MODELS[role_of(role)][0]
            total_worst += worst(role, s, u)
            total_likely += dollars(model, tokens_of(s + u), 0, EXPECTED_OUTPUT[role_of(role)])
    k = args.k
    print(f"{len(cases(args.split))} cases × arms {','.join(args.arms)} × k={k}: likely ${total_likely * k:.2f}, "
          f"worst ${total_worst * k:.2f} (first calls only: a repair or a re-task adds one author call each). "
          f"Spent so far ${ledger_total():.2f} of ${BUDGET_USD:.2f}.")
    return 0


def run_cases(selected: list[dict[str, Any]], arm: str, make_call: Any, folder: Path, *, conductor: Any = None
              ) -> list[dict[str, Any]]:
    rows = []
    for case in selected:
        call = make_call(case["id"])
        outcome = turn.run_turn(case, call, arm=arm)
        checks = turn.score(case, outcome)
        row = {"case": case["id"], "split": case["split"], "arm": arm, "passed": turn.passed(checks), "checks": checks,
               "outcome": outcome.data(), "ledger": turn.ledger_of(outcome)}
        if conductor is not None:
            doc = turn.fixture(case["scene"])
            message = case.get("message") or case["turns"][-1]["person"]
            answer = conductor(case["id"])("conductor", turn.conductor_system(),
                                           turn.conductor_message(doc, message, []), schema.conductor_schema())
            row["conductor"] = {"answer": answer, "checks": score_conductor(case, answer)}
        rows.append(row)
        (folder / f"{case['id']}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        mark = "PASS" if row["passed"] else "fail"
        print(f"{mark} {case['id']:<24} {json.dumps({k: v for k, v in checks.items() if v is not None})}")
    return rows


def next_folder(label: str) -> Path:
    RUNS.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.name.split("-")[0]) for p in RUNS.iterdir() if p.is_dir() and p.name.split("-")[0].isdigit()),
                default=0)
    folder = RUNS / f"{n}-{label}"
    folder.mkdir(parents=True)
    return folder


def cmd_offline(args: argparse.Namespace) -> int:
    folder = RUNS / "offline"
    folder.mkdir(parents=True, exist_ok=True)
    rows = run_cases(cases(args.split), args.arm, Recorded, folder)
    print(f"{sum(r['passed'] for r in rows)}/{len(rows)} pass on recorded answers (no model call)")
    return 0


def cmd_paid(args: argparse.Namespace) -> int:
    if not args.yes:
        print("A paid run costs money. Run `cost` and `dry` first, then run this again with --yes.")
        return 2
    if read_ledger() and not (args.hypothesis or "").strip():
        raise LabError("After the first run, a run needs --hypothesis: one change, one reason.")
    selected = cases(args.split, args.case)
    folder = next_folder(f"{args.arm}-{args.split or 'all'}")
    (folder / "notes.md").write_text(f"# Run {folder.name}\n\nHypothesis: {args.hypothesis or '(the first run)'}\n",
                                     encoding="utf-8")
    passes = []
    for k in range(args.k):
        rows = run_cases(selected, args.arm, lambda cid, k=k: Paid(folder.name, f"{cid}#{k}", args.hypothesis),
                         folder, conductor=(lambda cid: Paid(folder.name, cid, args.hypothesis)) if k == 0 else None)
        passes.append({r["case"]: r["passed"] for r in rows})
    every = {c["id"]: all(p.get(c["id"]) for p in passes) for c in selected}
    summary = {"arm": args.arm, "k": args.k, f"pass^{args.k}": sum(every.values()), "cases": len(selected),
               "spent": round(ledger_total(), 4), "budget": BUDGET_USD}
    (folder / "summary.json").write_text(json.dumps({**summary, "every": every}, indent=1), encoding="utf-8")
    print(json.dumps(summary))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    for r in read_ledger():
        print(f"{r['time']}  {r['run']:<16} {r['case']:<22} {r['role']:<18} ${float(r['dollars'] or 0):.4f} {r['status']}")
    print(f"total ${ledger_total():.2f} of ${BUDGET_USD:.2f}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """The blind page: for each case, the two end plans' changes as X and Y (which arm is which is in key.json)."""
    a, b = (Path(r) for r in args.run)
    import random
    rng = random.Random(args.seed)  # noqa: S311 (a shuffle for a blind page, not security)
    rows, key = [], {}
    for path in sorted(a.glob("*.json")):
        other = b / path.name
        if path.name in ("summary.json",) or not other.exists():
            continue
        one, two = json.loads(path.read_text(encoding="utf-8")), json.loads(other.read_text(encoding="utf-8"))
        pair = [one, two]
        rng.shuffle(pair)
        key[one["case"]] = {"X": pair[0]["arm"], "Y": pair[1]["arm"]}
        rows.append(f"## {one['case']}\n\n**X**\n" + "\n".join(f"- {c}" for c in pair[0]["outcome"]["changes"])
                    + "\n\n**Y**\n" + "\n".join(f"- {c}" for c in pair[1]["outcome"]["changes"])
                    + "\n\nWhich would you shoot? X / Y / same\n")
    out = a.parent / f"blind-{a.name}-vs-{b.name}"
    out.mkdir(exist_ok=True)
    (out / "page.md").write_text("# Which plan would you shoot?\n\n" + "\n".join(rows), encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    print(f"wrote {out / 'page.md'} (the key is in key.json: read it after you choose)")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lab/zora/run.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dry")
    d.add_argument("--case", default="approach-colder")
    d.add_argument("--arm", default="A", choices=("A", "B"))
    d.add_argument("--show", action="store_true", help="print the author's whole message")
    d.set_defaults(fn=cmd_dry)
    c = sub.add_parser("cost")
    c.add_argument("--split", default="", choices=("", "tune", "heldout"))
    c.add_argument("--arms", nargs="+", default=["A"], choices=("A", "B"))
    c.add_argument("--k", type=int, default=1)
    c.set_defaults(fn=cmd_cost)
    o = sub.add_parser("offline")
    o.add_argument("--split", default="", choices=("", "tune", "heldout"))
    o.add_argument("--arm", default="A", choices=("A", "B"))
    o.set_defaults(fn=cmd_offline)
    q = sub.add_parser("paid")
    q.add_argument("--yes", action="store_true")
    q.add_argument("--arm", default="A", choices=("A", "B"))
    q.add_argument("--split", default="tune", choices=("", "tune", "heldout"))
    q.add_argument("--case", default="")
    q.add_argument("--k", type=int, default=1)
    q.add_argument("--hypothesis", default="")
    q.set_defaults(fn=cmd_paid)
    sub.add_parser("ledger").set_defaults(fn=cmd_ledger)
    m = sub.add_parser("compare")
    m.add_argument("--run", nargs=2, required=True)
    m.add_argument("--seed", type=int, default=7)
    m.set_defaults(fn=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except LabError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
