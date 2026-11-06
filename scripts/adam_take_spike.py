"""The Phase 1 spike of plan/2026-11-05: is one take worth building, and where does each kind of fix start on the
ladder?

    python scripts/adam_take_spike.py --yes                       # variants A and B on three gold scenes (about $3)
    python scripts/adam_take_spike.py --yes --scene phone_call    # one scene
    python scripts/adam_take_spike.py --yes --variant B           # one variant

It refuses to start without `--yes`: it calls the real model about five times per scene and variant, and that costs
money.
A person starts it (the plan's rule), reads the table it writes and decides which variant to keep, whether Phases 2 to
4 stay as built, and where each kind of problem starts on the ladder (`systems/adam/adam_shot_planner/fixer.yaml`).

    A   one take, the full `TakeWire`, gpt-5 at medium effort, with no facts about the clock in the prompt
    B   A plus the facts code already knows (each line's words and the shortest take that holds it: plan §6 L2)
    C   think-then-type (plan §6 L1): NOT built. It needs a breakdown wire and a typist agent, and the plan keeps it
    only if
        A and B do not reach the cost target; this table says whether they do.

For each run it saves the plan (`tests/eval/adam/spike/<variant>/<scene>.json`) and its calls, scores the plan with
today's code (the same score, coverage and fidelity the live runner reads), and records what it cost and how much of
the answer was hidden reasoning. The fixer ladder runs on the problems code finds in each plan (the small tier first,
the big tier for any fix code refuses), and the table counts, per kind of problem, how many small-model fixes code
accepted. That count is what decides where a kind starts. The table is written to `tests/eval/adam/spike/summary.md`
for `IMPLEMENTED.md`, next to the staged runs already saved under `tests/eval/adam/live/`. Nothing is written to a
database, and no number here is made up: an empty cell means no run finished.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import adam_cost  # noqa: E402
import adam_live  # noqa: E402

SPIKE = ROOT / "tests" / "eval" / "adam" / "spike"
VARIANTS = {"A": {"facts": False}, "B": {"facts": True}}
SCENES = 3  # the gold scenes the spike runs on when none is named (not the one the prompt's own example shows)


def pick(names: list[str]) -> list[str]:
    from tests.adam import stages

    rest = [n for n in names if n != stages.EXAMPLE_SCENE]
    return (["phone_call"] if "phone_call" in rest else []) + [n for n in rest if n != "phone_call"][: SCENES - 1]


def run_variant(variant: str, name: str) -> dict[str, Any]:
    """One take of one scene, with the critic and the ladder; the row the table is made from."""
    from tests.adam import gold, stages

    from contracts.adam.plan import SceneScript
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.adam.adam_shot_planner.scene import Planner

    script = SceneScript.model_validate(gold.scene(name))
    line_ids = {b.line_id: b.line_id for b in script.lines if b.line_id}
    usage: list[dict[str, Any]] = []
    planner = Planner(RunContext(usage_sink=usage.append, usage_detail=True), script,
                      context={"heading": stages.title(name)}, line_ids=line_ids, removed=[], screening=True,
                      editorial=True)
    planner.facts = bool(VARIANTS[variant]["facts"])
    planned = planner.plan_take()
    folder = SPIKE / variant
    folder.mkdir(parents=True, exist_ok=True)
    saved = json.dumps(planned.stored.data(), ensure_ascii=False, indent=2)
    (folder / f"{name}.json").write_text(saved, encoding="utf-8")
    (folder / f"{name}.usage.json").write_text(json.dumps(usage, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{variant} {name}: {len(usage)} model calls\n{adam_cost.table(usage)}", flush=True)
    take = next((a for a in adam_cost.by_agent(usage) if a["agent"] == "adam_take"), {})
    return {**adam_live.row_of(name, planned, usage), "variant": variant, "thought": take.get("reasoning", 0),
            "written": take.get("output", 0),
            "tries": [{"kind": f["kind"], **t} for f in (planned.stored.report.get("fixer") or {}).get("problems") or []
                      for t in f["tries"]]}


def accept_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, tuple[int, int]]]:
    """Per kind of problem and rung: (fixes code accepted, fixes tried). The small model's rate is what decides where a
    kind starts on the ladder."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    for r in rows:
        for t in r.get("tries") or []:
            by_rung = out.setdefault(t["kind"], {})
            ok, n = by_rung.get(t["name"], (0, 0))
            by_rung[t["name"]] = (ok + int(bool(t["stood"])), n + 1)
    return out


def median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(values), 3) if values else None


def staged(names: list[str]) -> list[dict[str, Any]]:
    """The staged runs already saved by `adam_live.py` (no cost: they were not priced when they were made)."""
    rows = []
    for name in names:
        path = adam_live.LIVE / f"{name}.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            report = saved.get("report") or {}
            rows.append({"percent": (report.get("score") or {}).get("percent"),
                         "coverage": (report.get("coverage") or {}).get("coverage"),
                         "breaks": (report.get("fidelity") or {}).get("counts", {}).get("breaks"),
                         "overruns": (report.get("fit") or {}).get("overruns")})
    return rows


def summary(rows: list[dict[str, Any]], names: list[str]) -> str:
    cells = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
    head = ("| Variant | Runs | Score % (median) | Coverage (median) | Breaks | Overruns | Take thought (tokens) "
            "| $ a scene |")
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    saved = staged(names)
    if saved:
        lines.append(f"| staged (saved live runs, not priced) | {len(saved)} | {cells(median(saved, 'percent'))} | "
                     f"{cells(median(saved, 'coverage'))} | {sum(int(r['breaks'] or 0) for r in saved)} | "
                     f"{sum(int(r['overruns'] or 0) for r in saved)} | | 0.52 measured on 2026-11-04 |")
    for variant in sorted({r["variant"] for r in rows}):
        mine = [r for r in rows if r["variant"] == variant and not r.get("error")]
        lines.append(f"| {variant} | {len(mine)} | {cells(median(mine, 'percent'))} | "
                     f"{cells(median(mine, 'coverage'))} | "
                     f"{sum(int(r['breaks'] or 0) for r in mine)} | {sum(int(r['overruns'] or 0) for r in mine)} | "
                     f"{cells(median(mine, 'thought'))} | {cells(median(mine, 'cost'))} |")
    lines += ["", "| Kind of problem | Rung | Fixes code accepted | Tried |", "|---|---|---|---|"]
    for kind, by_rung in sorted(accept_rates(rows).items()):
        for rung, (ok, n) in sorted(by_rung.items()):
            lines.append(f"| {kind} | {rung} | {ok} | {n} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="yes, spend the model calls (about $3)")
    parser.add_argument("--scene", action="append", help="a gold scene (default: three)")
    parser.add_argument("--variant", choices=sorted(VARIANTS), action="append", help="A or B (default: both)")
    args = parser.parse_args(argv)
    if not args.yes:
        print("This calls the real model about five times per scene and variant (about $3 for the default run). "
              "Run again with --yes to go ahead.")
        return 2
    from tests.adam import gold

    names = args.scene or pick(gold.names())
    rows: list[dict[str, Any]] = []
    for variant in args.variant or sorted(VARIANTS):
        for name in names:
            try:
                rows.append(run_variant(variant, name))
            except Exception as exc:  # a scene the take cannot plan is a result, not a crash
                rows.append({"variant": variant, "scene": name, "error": f"{type(exc).__name__}: {exc}"[:160]})
            print({k: v for k, v in rows[-1].items() if k != "tries"}, flush=True)
    table = summary(rows, names)
    SPIKE.mkdir(parents=True, exist_ok=True)
    (SPIKE / "summary.md").write_text(table + "\n", encoding="utf-8")
    print("\n" + table + "\n\nVariant C (think-then-type) is not built; see this script's docstring.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
