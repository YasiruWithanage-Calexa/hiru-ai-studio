"""The Raphael lab's one tool (plan/2026-11-08e phase 0).

    python lab/raphael/run.py dry                          what a paid run would send and the most it could cost (free)
    python lab/raphael/run.py rehearse                     the whole loop with NO model: scripted answers (free)
    python lab/raphael/run.py paid --yes --hypothesis "…"  a real run (costs money; read `dry` first; ask the person first)
    python lab/raphael/run.py pick [--run DIR]             choose the small part for the post team to cut (free)
    python lab/raphael/run.py ledger                       every paid call so far and the total (free)

Run it with `OPENAI__API_KEY=` blank for everything but `paid`: only `paid` reads `.env` and builds a client. The money rules
are DaVinci's code (davinci/money.py) with Raphael's OWN ledger: a run stops at $5.00 of model tokens and this lab never passes
$5.00 in all. Stop after 3 paid runs for the person's read (phase 0b).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # started as a script: put the repo's import roots on the path
    _ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_ROOT / "lab"), str(_ROOT / "src" / "libs"), str(_ROOT / "src")]

from cinematic import pack
from davinci import checks, money
from davinci import run as davinci_run
from hiru_ai.core.tokens import tokens_of
from raphael import agent, rehearsal, render, schema

LAB = Path(__file__).resolve().parent
RUNS = LAB / "runs"
LEDGER = RUNS / "ledger.csv"  # Raphael's own: the plan gives this lab its own $5
PAID_RUNS_BEFORE_READ = 3  # phase 0b: stop after three paid runs for the person's read
EXPECTED_TURNS = 8  # what `dry` quotes as a likely run; the caps are what is enforced


def config(args: argparse.Namespace) -> agent.Config:
    m = [*args.model.split(":"), "high"][:2]
    return agent.Config(model=(m[0], m[1]), max_output=args.max_output, max_turns=args.max_turns)


def next_folder(label: str) -> Path:
    numbers = [int(m.group(1)) for p in RUNS.glob("*/") if (m := re.match(r"(\d+)-", p.name))]
    return RUNS / f"{max(numbers, default=0) + 1}-{re.sub(r'[^A-Za-z0-9.]+', '_', label)}"


def paid_runs() -> list[str]:
    return sorted({r["run"] for r in money.Meter(LEDGER, "count").rows()})


def write_result(folder: Path, reading: pack.Reading, raph: agent.Raphael, out: agent.Outcome, meter: money.Meter,
                 source: str, jonathan: dict[str, Any] | None) -> None:
    raph.work.dump(folder)
    n = raph.work.counts()
    (folder / "outcome.json").write_text(json.dumps({
        "stopped": out.stopped, "complete": out.finished, "turns": out.turns, "detail": out.detail,
        "editor_notes": out.editor_notes, "take_s": n["take_s"], "target_s": reading.guide_s, "cap_s": checks.limit_s(reading),
        "faults": [f.model_dump() for f in out.faults]}, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "usage.json").write_text(json.dumps({"run_dollars": round(meter.spent, 4), "calls": meter.calls,
                                                   "run_cap": meter.run_cap}, indent=1), encoding="utf-8")
    if raph.work.edit is not None:
        raph.work.edit = raph.work.edit.model_copy(update={"editor_notes": out.editor_notes or raph.work.edit.editor_notes})
    if not out.finished:  # D1 (recommended): save what it has, marked incomplete
        source = f"INCOMPLETE: the run stopped ({out.stopped}) before `finish`. {source}"
    (folder / "bin.html").write_text(render.build(reading, raph.work, out.faults, out.stopped, out.detail, source, jonathan,
                                                  out.turns), encoding="utf-8")


def summary(out: agent.Outcome, raph: agent.Raphael, meter: money.Meter, folder: Path) -> None:
    n = raph.work.counts()
    print(f"{folder.name}: {out.stopped} after {out.turns} turn(s). {out.detail}".strip())
    print(f"bin: {n['clips']} clips: {n['must']} must, {n['should']} should, {n['nice']} nice; {n['take_s']} s of takes "
          f"(target {raph.reading.guide_s:g} s, cap {checks.limit_s(raph.reading):g} s)")
    blocking = checks.blocking(out.faults)
    print(f"faults: {len(blocking)} blocking, {len(out.faults) - len(blocking)} report(s)")
    for f in out.faults:
        print("  " + f.line())
    print(f"model calls {meter.calls}, run ${meter.spent:.4f} of the ${meter.run_cap:.2f} cap; read {folder / 'bin.html'}")


# ── commands ─────────────────────────────────────────────────────────────────────────────────────


def cmd_dry(args: argparse.Namespace) -> int:
    reading = pack.load(davinci_run.scene_path(args.scene))
    cfg = config(args)
    raph = agent.Raphael(reading, rehearsal.Rehearsal(), money.Meter(RUNS / "dry.csv", "dry"), RUNS / "dry", cfg)
    specs = agent.tool_specs()
    first = tokens_of(raph.system + raph.opening + json.dumps(specs))
    print(f"=== prompt ({len(raph.system)} characters) ===\n{raph.system}\n")
    print(f"=== first message ({len(raph.opening)} characters) ===\n{raph.opening}\n")
    print("=== tools: " + ", ".join(s["name"] for s in specs) + f" ({len(json.dumps(specs))} characters of schemas; "
          f"put_clips alone {len(json.dumps(schema.put_schema()))})")
    model, effort = cfg.model
    if money.listed_price(model) is None:
        print(f"model {model} has no price in PRICES (cinematic/run.py): add it before a paid run.")
        return 1
    turn = money.worst_case(model, first, cfg.max_output)
    late = money.worst_case(model, first + 60_000, cfg.max_output)
    likely = sum(money.dollars(model, first + 6_000 * t, max(first + 6_000 * (t - 1), 0), 9_000) for t in range(EXPECTED_TURNS))
    print(f"model {model} ({effort}): the lab's default (D7 is the person's); max_output {cfg.max_output}, turn cap {cfg.max_turns}")
    print(f"first message about {first} tokens. WORST case of the first turn ${turn:.2f}; of a late turn (+60k context) ${late:.2f}")
    print(f"likely whole run (about {EXPECTED_TURNS} turns, ~9k output each, cached input): ${likely:.2f}  [a guess, not a measure]")
    meter = money.Meter(LEDGER, "dry")
    print(f"spent so far in this lab ${meter.ledger_total():.2f} in {len(paid_runs())} paid run(s); run cap "
          f"${money.RUN_CAP_USD:.2f}; lab budget ${money.LAB_BUDGET_USD:.2f}")
    try:
        meter.guard(model, first, cfg.max_output)
    except (money.LabError, money.CapReached) as exc:
        print(str(exc))
        return 1
    print("A paid run is allowed by the money rules. It still needs the person's yes.")
    return 0


def cmd_rehearse(args: argparse.Namespace) -> int:
    reading = pack.load(davinci_run.scene_path(args.scene))
    folder = RUNS / "rehearsal"
    if folder.exists():
        for f in folder.glob("*"):
            if f.is_file():
                f.unlink()
    meter = money.Meter(folder / "pretend_ledger.csv", "rehearsal")  # pretend dollars: a ledger of its own, never the lab's
    backend = rehearsal.Rehearsal()
    raph = agent.Raphael(reading, backend, meter, folder, config(args))
    backend.bind(raph)
    out = raph.run()
    source = ("REHEARSAL: no model wrote this. The edit plan, the clips and their designs are DaVinci's hand-written tables run "
              "through Raphael's real loop, tools and checks, so this page shows the SHAPE of the result, not the quality of a "
              "model's. The dollars are pretend.")
    write_result(folder, reading, raph, out, meter, source, davinci_run.jonathan_plan(args.jonathan))
    summary(out, raph, meter, folder)
    return 0 if out.finished and not checks.blocking(out.faults) else 1


def cmd_paid(args: argparse.Namespace) -> int:
    if not args.yes:
        print("A paid run costs money. Read `dry` first, then run this again with --yes (and the person's yes).")
        return 2
    done = paid_runs()
    if done and not (args.hypothesis or "").strip():
        raise money.LabError("After the first run, a run needs --hypothesis: one change, one reason.")
    if len(done) >= PAID_RUNS_BEFORE_READ and not args.past_read:
        raise money.LabError(f"{len(done)} paid runs are done: phase 0b stops here for the person's read (--past-read only "
                             "after their yes).")
    reading = pack.load(davinci_run.scene_path(args.scene))
    cfg = config(args)
    folder = next_folder(f"{cfg.model[0]}_{cfg.model[1]}-{args.scene}")
    meter = money.Meter(LEDGER, folder.name, hypothesis=args.hypothesis or "(the first run)")
    from cinematic.run import client  # the only place the lab builds a client, and it reads .env
    from davinci.brain import OpenAIBackend

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.md").write_text(f"# Run {folder.name}\n\nHypothesis: {args.hypothesis or '(the first run)'}\n\n"
                                     f"Model {cfg.model}, max_output {cfg.max_output}, turn cap {cfg.max_turns}.\n", encoding="utf-8")
    raph = agent.Raphael(reading, OpenAIBackend(client()), meter, folder, cfg)
    out = raph.run()
    write_result(folder, reading, raph, out, meter, f"A real run: {cfg.model[0]} ({cfg.model[1]}). Model tokens "
                 f"${meter.spent:.2f}.", davinci_run.jonathan_plan(args.jonathan))
    summary(out, raph, meter, folder)
    return 0 if out.finished else 1


def cmd_pick(args: argparse.Namespace) -> int:
    folder = Path(args.run) if args.run else RUNS / "rehearsal"
    return davinci_run.cmd_pick(argparse.Namespace(run=str(folder)))


def cmd_ledger(args: argparse.Namespace) -> int:
    meter = money.Meter(LEDGER, "ledger")
    for r in meter.rows():
        print(f"{r['time']}  {r['run']:<26} {r['slot']:<10} ${float(r['dollars'] or 0):7.4f}  {r['status']}  {r['hypothesis']}")
    print(f"total ${meter.ledger_total():.2f} of ${money.LAB_BUDGET_USD:.2f} in {len(paid_runs())} paid run(s)")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("dry", cmd_dry), ("rehearse", cmd_rehearse), ("paid", cmd_paid)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--scene", default="episode1", help="a lab key or a yaml path")
        p.add_argument("--model", default="gpt-5:high", help="model:effort (D7: the person's choice)")
        p.add_argument("--max-output", type=int, default=48_000)
        p.add_argument("--max-turns", type=int, default=20)
        p.add_argument("--jonathan", default="", help="a Jonathan plan_mended.json to compare with (default: cinematic run 17)")
        if name == "paid":
            p.add_argument("--yes", action="store_true")
            p.add_argument("--hypothesis", default="")
            p.add_argument("--past-read", action="store_true", help="a fourth run or later: only after the person's read")
    p = sub.add_parser("pick")
    p.set_defaults(fn=cmd_pick)
    p.add_argument("--run", default="")
    sub.add_parser("ledger").set_defaults(fn=cmd_ledger)
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except money.LabError as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
