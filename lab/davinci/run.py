"""The DaVinci lab's one tool (plan/2026-11-08d phase 0 and PLAN-B.md).

    python lab/davinci/run.py dry                          what a paid run would send and the most it could cost (free)
    python lab/davinci/run.py rehearse                     the whole run with NO model: scripted answers (free)
    python lab/davinci/run.py paid --yes --hypothesis "…"  a real run (costs money; read `dry` first; ask the person first)
    python lab/davinci/run.py pick [--run DIR]             choose the small part for the post team to cut (free)
    python lab/davinci/run.py ledger                       every paid call so far and the total (free)

`--mode staged` (the default, plan B: plan, repair, design, re-design) or `--mode orchestrator` (the director's tool loop of runs
1 and 2, kept as their record) applies to `dry`, `rehearse` and `paid`.

Run it with `OPENAI__API_KEY=` blank for everything but `paid`: only `paid` reads `.env` and builds a client. The money
rules are code (money.py): a run stops at $5.00 of model tokens (the plan's cap) and the lab never passes $5.00 in all.
Generating the sample clips with Veo and giving them to the post team are the person's (phase 0).
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
from cinematic.run import INPUT as CINEMATIC_INPUT
from davinci import checks, money, orchestrator, rehearsal, render, schema, stages
from davinci.state import Bin
from hiru_ai.core.tokens import tokens_of

LAB = Path(__file__).resolve().parent
RUNS = LAB / "runs"
LEDGER = RUNS / "ledger.csv"
SCENES = {"episode1": CINEMATIC_INPUT / "reading.yaml", "second": CINEMATIC_INPUT / "second_scene.yaml"}
JONATHAN = LAB.parent / "cinematic" / "runs" / "17-gpt_5-high" / "plan_mended.json"  # the cinematic lab's best plan of Episode 1
EXPECTED_DIRECTOR_TURNS, EXPECTED_WORKER_CALLS = 14, 8  # what the dry run quotes as a likely run; the cap is what is enforced


def scene_path(name: str) -> Path:
    if name in SCENES:
        return SCENES[name]
    if Path(name).is_file():
        return Path(name)
    raise money.LabError(f"Unknown scene {name!r}: use {sorted(SCENES)} or a yaml path.")


def config(args: argparse.Namespace) -> orchestrator.Config:
    d, w = [*args.director.split(":"), "medium"][:2], [*args.worker.split(":"), "medium"][:2]
    return orchestrator.Config(director=(d[0], d[1]), worker=(w[0], w[1]),
                               director_max_output=args.director_max_output or orchestrator.Config.director_max_output,
                               worker_max_output=args.worker_max_output, max_turns=args.max_turns)


def staged_config(args: argparse.Namespace) -> stages.Config:
    d, w = [*args.director.split(":"), "medium"][:2], [*args.worker.split(":"), "medium"][:2]
    return stages.Config(director=(d[0], d[1]), worker=(w[0], w[1]),
                         director_max_output=args.director_max_output or stages.Config.director_max_output,
                         worker_max_output=args.worker_max_output, batch=args.batch, threads=args.threads,
                         repair_rounds=args.repair_rounds, redesign_rounds=args.redesign_rounds)


def next_folder(label: str) -> Path:
    numbers = [int(m.group(1)) for p in RUNS.glob("*/") if (m := re.match(r"(\d+)-", p.name))]
    return RUNS / f"{max(numbers, default=0) + 1}-{re.sub(r'[^A-Za-z0-9.]+', '_', label)}"


def jonathan_plan(path: str) -> dict[str, Any] | None:
    p = Path(path) if path else JONATHAN
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def write_result(folder: Path, reading: pack.Reading, work: Bin, out: orchestrator.Outcome, meter: money.Meter, source: str,
                 jonathan: dict[str, Any] | None) -> None:
    """Stage 5 (or the orchestrator's end): the bin, the plan, the outcome with each stage's time, calls and dollars, the page."""
    stage_rows = getattr(out, "stages", None)
    work.dump(folder)
    (folder / "outcome.json").write_text(json.dumps({"stopped": out.stopped, "detail": out.detail, "editor_notes": out.editor_notes,
                                                     "faults": [f.model_dump() for f in out.faults],
                                                     **({"stages": stage_rows} if stage_rows else {})}, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    (folder / "usage.json").write_text(json.dumps({"run_dollars": round(meter.spent, 4), "calls": meter.calls,
                                                   "run_cap": meter.run_cap}, indent=1), encoding="utf-8")
    if work.edit is not None:
        work.edit = work.edit.model_copy(update={"editor_notes": out.editor_notes or work.edit.editor_notes})
    (folder / "bin.html").write_text(render.build(reading, work, out.faults, out.stopped, out.detail, source, jonathan, stage_rows),
                                     encoding="utf-8")


def summary(out: orchestrator.Outcome, work: Bin, meter: money.Meter, folder: Path) -> None:
    n = work.counts()
    print(f"{folder.name}: {out.stopped}. {out.detail}".strip())
    print(f"bin: {n['clips']} clips ({n['written']} designed): {n['must']} must, {n['should']} should, {n['nice']} nice; "
          f"{n['take_s']} s of takes")
    blocking = checks.blocking(out.faults)
    print(f"faults: {len(blocking)} blocking, {len(out.faults) - len(blocking)} report(s)")
    for f in out.faults:
        print("  " + f.line())
    for st in getattr(out, "stages", None) or []:
        print(f"  stage {st['stage']:<9} {st['start']}-{st['end']} {st['seconds']:>6g} s  {st['calls']:>2} call(s)  "
              f"${st['dollars']:.4f}  {st['detail']}")
    print(f"model calls {meter.calls}, run ${meter.spent:.4f} of the ${meter.run_cap:.2f} cap; read {folder / 'bin.html'}")


# ── commands ─────────────────────────────────────────────────────────────────────────────────────


def cmd_dry_staged(args: argparse.Namespace) -> int:
    reading = pack.load(scene_path(args.scene))
    cfg = staged_config(args)
    runner = stages.Stages(reading, rehearsal.StagedRehearsal(), money.Meter(RUNS / "dry.csv", "dry"), RUNS / "dry", cfg)  # never called
    system = orchestrator.prompt("director_plan")
    opening = runner.opening()
    sch = schema.plan_schema()
    first = tokens_of(system + opening + json.dumps(sch))
    print(f"=== director prompt ({len(system)} characters) ===\n{system}\n")
    print(f"=== stage 1 message ({len(opening)} characters) ===\n{opening}\n")
    print(f"=== plan schema: {len(json.dumps(sch))} characters; clip designs schema: {len(json.dumps(schema.ir_list_schema()))} characters")
    print(f"prompts: repair {len(orchestrator.prompt('director_repair'))}, clip writer {len(orchestrator.prompt('clip_writer_staged'))} "
          "characters\n")
    dm, de = cfg.director
    wm, we = cfg.worker
    for label, model in (("director", dm), ("worker", wm)):
        if money.listed_price(model) is None:
            print(f"{label} model {model} has no price in PRICES (cinematic/run.py): add it before a paid run.")
            return 1
    worst = stages.worst_case_run(reading, cfg, money.worst_case)
    print(f"director {dm} ({de}), worker {wm} ({we}): the lab's defaults; the models are the person's choice (D7)")
    print(f"limits: director output {cfg.director_max_output}, worker output {cfg.worker_max_output}, repair rounds "
          f"{cfg.repair_rounds}, re-design rounds {cfg.redesign_rounds}, {cfg.threads} threads, {cfg.batch} clips a call")
    print("WORST case of the whole run (every call spends every output token; the clip count is the most the length limit allows):")
    for name, dollars in worst:
        print(f"  {name:<9} ${dollars:.2f}")
    ledger = money.Meter(LEDGER, "dry").ledger_total()
    print(f"  total     ${sum(d for _, d in worst):.2f}   [the run stops at ${money.RUN_CAP_USD:.2f}; the lab has "
          f"${money.LAB_BUDGET_USD - ledger:.2f} left]")
    likely = (money.dollars(dm, 12_000, 0, 18_000) + 0.5 * money.dollars(dm, 40_000, 0, 18_000)
              + 7 * money.dollars(wm, 9_000, 0, 9_000) + money.dollars(wm, 9_000, 0, 5_000))
    print(f"likely whole run: about ${likely:.2f} (1 plan call, half a repair, 7 designs, 1 re-design)  [a guess, not a measure; "
          "the plan's own table says $0.30-0.80]")
    print(f"spent so far in the lab ${ledger:.2f}; run cap ${money.RUN_CAP_USD:.2f}; lab budget ${money.LAB_BUDGET_USD:.2f}")
    try:
        money.Meter(LEDGER, "dry").guard(dm, first, cfg.director_max_output)
    except (money.LabError, money.CapReached) as exc:
        print(str(exc))
        return 1
    print("A paid run is allowed by the money rules. It still needs the person's yes.")
    return 0


def cmd_dry(args: argparse.Namespace) -> int:
    if args.mode == "staged":
        return cmd_dry_staged(args)
    reading = pack.load(scene_path(args.scene))
    cfg = config(args)
    backend = rehearsal.Rehearsal()  # never called: dry only builds the messages
    orch = orchestrator.Orchestrator(reading, backend, money.Meter(RUNS / "dry.csv", "dry"), RUNS / "dry", cfg)
    specs = orchestrator.tool_specs()
    note = orch.length_note()
    opening = f"{orch.base}\n\n" + (f"{note}\n\n" if note else "") + "Plan this scene. Start with the intended cut."
    first = tokens_of(orch.system + opening + json.dumps(specs))
    print(f"=== director prompt ({len(orch.system)} characters) ===\n{orch.system}\n")
    print(f"=== first message ({len(opening)} characters) ===\n{opening}\n")
    print("=== tools: " + ", ".join(s["name"] for s in specs) + f" ({len(json.dumps(specs))} characters of schemas)")
    for name, sch in (("coverage menu", schema.menu_schema()), ("clip designs", schema.ir_list_schema())):
        print(f"=== worker schema {name}: {len(json.dumps(sch))} characters")
    print(f"worker prompts: coverage {len(orchestrator.prompt('coverage'))}, clip writer {len(orchestrator.prompt('clip_writer'))} characters\n")
    dm, de = cfg.director
    wm, we = cfg.worker
    for label, model in (("director", dm), ("worker", wm)):
        if money.listed_price(model) is None:
            print(f"{label} model {model} has no price in PRICES (cinematic/run.py): add it before a paid run.")
            return 1
    d_turn = money.worst_case(dm, first, cfg.director_max_output)
    w_call = money.worst_case(wm, first + 6000, cfg.worker_max_output)
    likely = (EXPECTED_DIRECTOR_TURNS * money.dollars(dm, 12_000, 8_000, 2_500) + EXPECTED_WORKER_CALLS * money.dollars(wm, 9_000, 0, 9_000))
    print(f"director {dm} ({de}), worker {wm} ({we}): the lab's defaults; the models are the person's choice (D7)")
    print(f"WORST case of the first director turn ${d_turn:.2f}; of one worker call ${w_call:.2f} (every output token spent)")
    print(f"likely whole run (about {EXPECTED_DIRECTOR_TURNS} director turns, {EXPECTED_WORKER_CALLS} worker calls): ${likely:.2f}  [a guess, not a measure]")
    ledger = money.Meter(LEDGER, "dry").ledger_total()
    print(f"spent so far in the lab ${ledger:.2f}; run cap ${money.RUN_CAP_USD:.2f}; lab budget ${money.LAB_BUDGET_USD:.2f}")
    try:
        money.Meter(LEDGER, "dry").guard(dm, first, cfg.director_max_output)
    except (money.LabError, money.CapReached) as exc:
        print(str(exc))
        return 1
    print("A paid run is allowed by the money rules. It still needs the person's yes.")
    return 0


def clear(folder: Path) -> None:
    if folder.exists():
        for f in folder.glob("*"):
            if f.is_file():
                f.unlink()


def cmd_rehearse_staged(args: argparse.Namespace) -> int:
    reading = pack.load(scene_path(args.scene))
    folder = RUNS / "rehearsal-staged"
    clear(folder)
    meter = money.Meter(folder / "pretend_ledger.csv", "rehearsal-staged")  # pretend dollars: a ledger of its own, never the lab's
    runner = stages.Stages(reading, rehearsal.StagedRehearsal(), meter, folder, staged_config(args))
    out = runner.run()
    source = ("REHEARSAL (staged): no model wrote this. The plan, the repair and the designs are hand-written tables run through the "
              "real stages, checks, mend, look sheet and money rules, so this page shows the SHAPE of the result, not the quality "
              "of a model's. The dollars and the seconds are pretend.")
    write_result(folder, reading, runner.work, out, meter, source, jonathan_plan(args.jonathan))
    summary(out, runner.work, meter, folder)
    return 0 if out.finished and not checks.blocking(out.faults) else 1


def cmd_rehearse(args: argparse.Namespace) -> int:
    if args.mode == "staged":
        return cmd_rehearse_staged(args)
    reading = pack.load(scene_path(args.scene))
    folder = RUNS / "rehearsal"
    clear(folder)
    meter = money.Meter(folder / "pretend_ledger.csv", "rehearsal")  # pretend dollars: a ledger of its own, never the lab's
    backend = rehearsal.Rehearsal()
    orch = orchestrator.Orchestrator(reading, backend, meter, folder, config(args))
    backend.bind(orch)
    out = orch.run()
    source = ("REHEARSAL: no model wrote this. The coverage, the designs and the director's calls are hand-written tables run "
              "through the real loop, tools and checks, so this page shows the SHAPE of the result, not the quality of a model's. "
              "The dollars are pretend.")
    write_result(folder, reading, orch.work, out, meter, source, jonathan_plan(args.jonathan))
    summary(out, orch.work, meter, folder)
    return 0 if out.finished and not checks.blocking(out.faults) else 1


def cmd_paid(args: argparse.Namespace) -> int:
    if not args.yes:
        print("A paid run costs money. Read `dry` first, then run this again with --yes (and the person's yes).")
        return 2
    meter0 = money.Meter(LEDGER, "pending")
    if meter0.rows() and not (args.hypothesis or "").strip():
        raise money.LabError("After the first run, a run needs --hypothesis: one change, one reason.")
    reading = pack.load(scene_path(args.scene))
    cfg: stages.Config | orchestrator.Config = staged_config(args) if args.mode == "staged" else config(args)
    folder = next_folder(f"{cfg.director[0]}-{args.scene}" + ("-staged" if args.mode == "staged" else ""))
    meter = money.Meter(LEDGER, folder.name, hypothesis=args.hypothesis or "(the first run)")
    from cinematic.run import client  # the only place the lab builds a client, and it reads .env
    from davinci.brain import OpenAIBackend

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.md").write_text(f"# Run {folder.name}\n\nMode: {args.mode}. Hypothesis: {args.hypothesis or '(the first run)'}\n\n"
                                     f"Director {cfg.director}, worker {cfg.worker}.\n", encoding="utf-8")
    runner: stages.Stages | orchestrator.Orchestrator
    if isinstance(cfg, stages.Config):
        runner = stages.Stages(reading, OpenAIBackend(client()), meter, folder, cfg)
    else:
        runner = orchestrator.Orchestrator(reading, OpenAIBackend(client()), meter, folder, cfg)
    out = runner.run()
    write_result(folder, reading, runner.work, out, meter, f"A real run ({args.mode}): director {cfg.director[0]}, worker "
                 f"{cfg.worker[0]}. Model tokens ${meter.spent:.2f}.", jonathan_plan(args.jonathan))
    summary(out, runner.work, meter, folder)
    return 0 if out.finished else 1


def pick_sample(clips: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The small part of phase 0: one moment from three angles, one transition pair, one drone or B-roll clip."""
    written = [c for c in clips if c.get("ir")]
    by_moment: dict[int, list[dict[str, Any]]] = {}
    for c in written:
        if c["role"] not in ("establishing", "atmosphere", "transition_out", "transition_in"):
            by_moment.setdefault(c["moment"], []).append(c)
    best: list[dict[str, Any]] = []
    for n in sorted(by_moment):
        mine = by_moment[n]
        sizes = {c["size"] for c in mine}
        if any(c["speaks"] for c in mine) and len(sizes) > len({c["size"] for c in best}):
            best = mine
    angles: list[dict[str, Any]] = []
    for c in sorted(best, key=lambda c: (c["priority"] != "must", c["priority"] != "should", c["id"])):
        if c["size"] not in {a["size"] for a in angles}:
            angles.append(c)
        if len(angles) == 3:
            break
    outs = [c for c in written if c["role"] == "transition_out"]
    ins = [c for c in written if c["role"] == "transition_in"]
    pair = next(([o, i] for o in outs for i in ins if o["technique"].split("_")[0] == i["technique"].split("_")[0]), [])
    broll = next((c for c in written if c["technique"].startswith("drone")), None) or next(
        (c for c in written if c["role"] in ("atmosphere", "establishing")), None)
    return {"angles": angles, "transition": pair, "broll": [broll] if broll else []}


def cmd_pick(args: argparse.Namespace) -> int:
    folder = Path(args.run) if args.run else RUNS / "rehearsal"
    clips = json.loads((folder / "bin.json").read_text(encoding="utf-8"))
    sample = pick_sample(clips)
    out = folder / "post_test"
    out.mkdir(exist_ok=True)
    lines = ["# The small part for the post team (plan/2026-11-08d phase 0)", "",
             "Generate these clips with Veo (in Hiru: a shot's take, Omni Flash or Veo 3.1; it needs RENDER_VIDEO). That is the "
             "person's to run and to pay for. Use ONE shared first-frame reference (the same picture of the place and the people) "
             "for the clips of the moment, and the same seed where the engine takes one, so the angles match.", ""]
    for title, key in (("One moment from three angles", "angles"), ("One transition pair", "transition"), ("One drone or B-roll clip", "broll")):
        lines += [f"## {title}", ""]
        if not sample[key]:
            lines += ["_The bin has no clip for this yet._", ""]
        for c in sample[key]:
            name = re.sub(r"[^A-Za-z0-9]+", "_", c["slate"])
            (out / f"{name}.json").write_text(json.dumps({k: c[k] for k in ("id", "slate", "role", "technique", "take_s", "handle_in_s", "handle_out_s", "lines", "speaks", "ir", "sound")}, ensure_ascii=False, indent=1), encoding="utf-8")
            lines.append(f"- **{c['slate']}** ({c['id']}): {c['role']}, {c['size']}, {c['technique']}, {c['take_s']} s "
                         f"(handles {c['handle_in_s']:g}/{c['handle_out_s']:g}); {c['why']}  → `post_test/{name}.json`")
        lines.append("")
    lines += ["## What to ask the post team", "",
              "1. Can you cut between the three angles on the action (do gestures and timing match)? Where does it break?",
              "2. Do the handles give you room, or are they wasted?",
              "3. Does the transition pair land (both halves)?", "4. Is the drone / B-roll clip usable, and would you ask for more of it?",
              "5. Against Jonathan's finished cut of the same scene: which would you rather start from, and what is missing?"]
    (folder / "post_test.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    meter = money.Meter(LEDGER, "ledger")
    for r in meter.rows():
        print(f"{r['time']}  {r['run']:<26} {r['slot']:<16} ${float(r['dollars'] or 0):7.4f}  {r['status']}  {r['hypothesis']}")
    print(f"total ${meter.ledger_total():.2f} of ${money.LAB_BUDGET_USD:.2f}")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("dry", cmd_dry), ("rehearse", cmd_rehearse), ("paid", cmd_paid)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        p.add_argument("--scene", default="episode1", help="a lab key or a yaml path")
        p.add_argument("--director", default="gpt-5:medium", help="model:effort of the director (D7: the person's choice)")
        p.add_argument("--worker", default="gpt-5-mini:medium", help="model:effort of the coverage planner and clip writer")
        p.add_argument("--mode", choices=("staged", "orchestrator"), default="staged",
                       help="staged (plan B, the default) or the orchestrator of runs 1-2 (kept as their record)")
        p.add_argument("--director-max-output", type=int, default=0, help="0: the mode's default (staged 32000, orchestrator 16000)")
        p.add_argument("--worker-max-output", type=int, default=20_000)
        p.add_argument("--max-turns", type=int, default=40, help="orchestrator mode only")
        p.add_argument("--threads", type=int, default=stages.Config.threads, help="staged: parallel clip-writer calls")
        p.add_argument("--batch", type=int, default=stages.Config.batch, help="staged: clips a clip writer designs in one call")
        p.add_argument("--repair-rounds", type=int, default=stages.Config.repair_rounds)
        p.add_argument("--redesign-rounds", type=int, default=stages.Config.redesign_rounds)
        p.add_argument("--jonathan", default="", help="a Jonathan plan_mended.json to compare with (default: cinematic run 17)")
        if name == "paid":
            p.add_argument("--yes", action="store_true")
            p.add_argument("--hypothesis", default="")
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
