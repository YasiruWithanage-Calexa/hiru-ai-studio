"""Shot Planner Adam on the gold scenes with the REAL model (plan/2026-11-04b section 10, plan/2026-11-04c
Phase 7): what only a live run can show.

    python scripts/adam_live.py --yes                         # every gold scene, one run each
    python scripts/adam_live.py --yes --runs 3                # three runs each: the median is what the exits judge
    python scripts/adam_live.py --yes --scene phone_call      # one
    python scripts/adam_live.py --yes --no-screening          # without the four critics and the revision

It refuses to start without `--yes`: a scene is about eleven model calls and they cost money, and models vary from run
to run, so one run proves little (plan/2026-11-04c asks for three). Nothing is written to a database (the planner needs
none); each plan is saved under `tests/eval/adam/live/<scene>.json` (`<scene>.run<N>.json` from the second run) and a
table says, per scene, the craft score of the final plan, the share of required faces seen (the coverage grid) and the
holes by name, whether the revision after screening won or was refused (and why), the moments left without a record,
the fidelity breaks and the overruns, and the density (moments per card, used shot length). Those are the numbers the
exits ask for: coverage of at least 90 %, 0 moments lost without a record, a revision that never loses a required cell,
the revised plan winning on score in at least 60 % of gold scenes and never losing fidelity. Whether the treatments
are a real director's ideas and whether the cards read like section 9 is a person's judgement, so the plans are saved
for a person to read and for `adam_ab.py`. Run it with the key in `.env` (OPENAI__API_KEY); the models are the
configured tiers.
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

LIVE = ROOT / "tests" / "eval" / "adam" / "live"
WINS_TARGET = 0.60
COVERAGE_TARGET = 0.90  # per scene, the median of the runs (plan/2026-11-04c Phase 7)


def row_of(name: str, planned: Any) -> dict[str, Any]:
    """The numbers one run gives, read from the plan's own report."""
    report = planned.stored.report
    screening = report.get("screening") or {}
    revision = screening.get("revision") or {}
    candidates = next((e for e in (report.get("history") or {}).get("events", []) if e.get("kind") == "kept"), {})
    lost = max((c.get("lost_cells", 0) for c in candidates.get("candidates", [])[1:]), default=0)
    coverage = report.get("coverage") or {}
    return {"scene": name, "percent": (report.get("score") or {}).get("percent"),
            "coverage": coverage.get("coverage"), "holes": [h["cell"] for h in coverage.get("holes") or []],
            "kept": screening.get("kept", ""), "refused": revision.get("invalid") or [],
            "revision_lost_cells": lost if screening.get("kept") == "revision" else 0,
            "unaccounted": len((report.get("ledger") or {}).get("unaccounted") or []),
            "breaks": (report.get("fidelity") or {}).get("counts", {}).get("breaks"),
            "overruns": (report.get("fit") or {}).get("overruns"), "cards": len(planned.stored.cards),
            "seconds": (report.get("fit") or {}).get("runtime_s"), "density": report.get("density"),
            "questions": [q["question"] for q in report.get("questions") or []]}


def run_scene(name: str, screening: bool, run: int = 1) -> dict[str, Any]:
    from tests.adam import gold, stages

    from contracts.adam.plan import SceneScript
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.adam.adam_shot_planner.scene import Planner

    script = SceneScript.model_validate(gold.scene(name))
    line_ids = {b.line_id: b.line_id for b in script.lines if b.line_id}
    planner = Planner(RunContext(), script, context={"heading": stages.title(name)}, line_ids=line_ids, removed=[],
                      screening=screening, editorial=True)
    planned = planner.plan()
    LIVE.mkdir(parents=True, exist_ok=True)
    saved = json.dumps(planned.stored.data(), ensure_ascii=False, indent=2)
    (LIVE / (f"{name}.json" if run == 1 else f"{name}.run{run}.json")).write_text(saved, encoding="utf-8")
    return row_of(name, planned)


def judge(rows: list[dict[str, Any]], names: list[str]) -> list[str]:
    """The Phase 7 exits, per scene, as the median of its runs: what passed and what did not."""
    out = []
    for name in names:
        mine = [r for r in rows if r["scene"] == name and not r.get("error")]
        if not mine:
            out.append(f"{name}: no run finished")
            continue
        cover = statistics.median(float(r["coverage"] or 0) for r in mine)
        lost = sum(int(r["unaccounted"]) for r in mine)
        refused = sum(int(r["revision_lost_cells"]) for r in mine)
        verdict = "ok" if cover >= COVERAGE_TARGET and not lost and not refused else "NOT MET"
        out.append(f"{name}: coverage {cover:.0%} (target {COVERAGE_TARGET:.0%}), {lost} moment(s) without a record "
                   f"(target 0), revisions that lost a required face: {refused} (target 0): {verdict}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="yes, spend the model calls")
    parser.add_argument("--scene", action="append", help="a gold scene (default: all)")
    parser.add_argument("--runs", type=int, default=1, help="runs per scene; the exits judge the median of three")
    parser.add_argument("--no-screening", action="store_true")
    args = parser.parse_args(argv)
    if not args.yes:
        print("This calls the real model about eleven times per scene and run. Run again with --yes to go ahead.")
        return 2
    from tests.adam import gold

    names = args.scene or gold.names()
    rows: list[dict[str, Any]] = []
    for name in names:
        for run in range(1, max(1, args.runs) + 1):
            try:
                rows.append(run_scene(name, not args.no_screening, run))
            except Exception as exc:  # a scene Adam cannot plan is a result, not a crash
                rows.append({"scene": name, "error": f"{type(exc).__name__}: {exc}"[:160]})
            print(rows[-1], flush=True)
    revised = [r for r in rows if r.get("kept")]
    won = sum(r["kept"] == "revision" for r in revised)
    broke = sum(bool(r.get("breaks")) for r in rows)
    print(f"\n{len(rows)} runs; the revision won on {won} of {len(revised)} "
          f"(target {WINS_TARGET:.0%}); {broke} with a fidelity break (target 0)")
    print("\n".join(judge(rows, names)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
