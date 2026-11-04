"""Shot Planner Adam: the blind A/B results against the plan's targets, and the score weights tuned to a person's picks
(plan/2026-11-04b §1, Phase 10).

    python scripts/adam_ab.py                       # summarise tests/eval/adam/ab_results/*.json
    python scripts/adam_ab.py --dir some/folder     # another folder of records
    python scripts/adam_ab.py --tune pairs.json     # suggest weights from {a, b, pick} records (see `tune`)

A record is `tests/eval/adam/ab_form.json` filled in: the scores of plan A and plan B on each lens, which one a Hiru
director would be proud of, and the key (filled in after the scores) saying which plan was classic, adam or master. This
script only COUNTS what people judged and checks the numbers against the targets; it decides nothing. Whether Adam
becomes the default for new productions is a person's call (Phase 10); the targets below are the plan's.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "tests" / "eval" / "adam" / "ab_results"

PREFER_ADAM = 0.80  # Adam preferred over script_split on at least this share of scenes
FELT_THERE = 4.0  # average "I felt I was there" for Adam
MUTE_TEST = 4.0  # average mute test for Adam
BEATS_MASTER = 0.40  # Adam judged as good as or better than the master on at least this share of scenes
GRID = (0.5, 1.0, 2.0)  # the weights a signal may take while tuning; equal weights (1.0) are where it starts


def load(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]


def _sides(record: dict[str, Any]) -> dict[str, str] | None:
    key = record.get("key") or {}
    sides = {slot: str(key.get(slot, "")).strip().lower() for slot in ("A", "B")}
    return sides if all(sides.values()) else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The plan's measures from the records that have a key and a choice. A record without either is counted as open."""
    versus: dict[str, list[bool]] = {"classic": [], "master": []}  # per scene: was Adam the one preferred / good enough
    felt: list[float] = []
    mute: list[float] = []
    open_records = 0
    for r in records:
        sides = _sides(r)
        pick = str(r.get("proud_of") or "")
        if sides is None or pick not in ("A", "B", "neither"):
            open_records += 1
            continue
        adam = next((slot for slot, who in sides.items() if who == "adam"), None)
        other = next((who for who in sides.values() if who in versus), None)
        if adam is None or other is None:
            continue
        scores = (r.get("scores") or {}).get(adam) or {}
        if isinstance(scores.get("felt_there"), (int, float)):
            felt.append(float(scores["felt_there"]))
        if isinstance(scores.get("mute_test"), (int, float)):
            mute.append(float(scores["mute_test"]))
        if other == "master":  # as good as or better: preferred, or no worse on "felt there"
            theirs = (r.get("scores") or {}).get("B" if adam == "A" else "A") or {}
            ours, them = scores.get("felt_there"), theirs.get("felt_there")
            versus["master"].append(pick == adam or (isinstance(ours, (int, float)) and isinstance(them, (int, float))
                                                     and ours >= them))
        else:
            versus["classic"].append(pick == adam)
    share = {k: (round(sum(v) / len(v), 2) if v else None) for k, v in versus.items()}
    felt_avg, mute_avg = _mean(felt), _mean(mute)
    checks = {
        "adam_preferred_over_classic": (share["classic"], PREFER_ADAM, len(versus["classic"])),
        "felt_there_average": (felt_avg, FELT_THERE, len(felt)),
        "mute_test_average": (mute_avg, MUTE_TEST, len(mute)),
        "as_good_as_master": (share["master"], BEATS_MASTER, len(versus["master"])),
    }
    return {"records": len(records), "open": open_records,
            "targets": {name: {"value": value, "target": target, "judged": n,
                               "met": (value is not None and value >= target) if n else None}
                        for name, (value, target, n) in checks.items()}}


def tune(pairs: list[dict[str, Any]], signals: list[str] | None = None, rounds: int = 3) -> dict[str, float]:
    """Weights that agree with a person's picks more often than equal ones do.

    `pairs`: `{"a": {signal: share of its points earned, 0..1}, "b": {...}, "pick": "a" | "b"}`, one per judged pair
    (the shares come from `adam_score`: each signal's `points / weight`). Coordinate ascent over `GRID`, one signal at a
    time; a change is kept only if it makes strictly more picks agree, so a signal no pick depends on stays at 1.0.
    """
    names = signals or sorted({s for p in pairs for side in ("a", "b") for s in p[side]})
    weights = dict.fromkeys(names, 1.0)

    def agree(w: dict[str, float]) -> int:
        def total(side: dict[str, float]) -> float:
            return sum(w[s] * side.get(s, 0.0) for s in names)

        return sum((total(p["a"]) > total(p["b"])) == (p["pick"] == "a") and total(p["a"]) != total(p["b"])
                   for p in pairs)

    best = agree(weights)
    for _ in range(rounds):
        changed = False
        for name in names:
            for candidate in GRID:
                if candidate == weights[name]:
                    continue
                trial = {**weights, name: candidate}
                score = agree(trial)
                if score > best:
                    weights, best, changed = trial, score, True
        if not changed:
            break
    return weights


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=RESULTS)
    parser.add_argument("--tune", type=Path, help="a JSON list of {a, b, pick} records; prints suggested weights")
    args = parser.parse_args(argv)
    if args.tune:
        print(json.dumps(tune(json.loads(args.tune.read_text(encoding="utf-8"))), indent=2))
        return 0
    if not args.dir.is_dir():
        print(f"no results yet: {args.dir} does not exist (copy tests/eval/adam/ab_form.json there, one per judgement)")
        return 0
    result = summarise(load(args.dir))
    print(f"{result['records']} records ({result['open']} not yet judged or not yet keyed)")
    for name, row in result["targets"].items():
        state = "no data" if row["met"] is None else ("MET" if row["met"] else "not met")
        print(f"  {name:30s} {row['value']!s:>6} vs target {row['target']:<5} over {row['judged']:>2}  {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
