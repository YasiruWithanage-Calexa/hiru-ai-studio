"""The Raphael lab's one tool (plan/2026-11-08e phase 0).

    python lab/raphael/run.py dry                          what a paid run would send and the most it could cost (free)
    python lab/raphael/run.py rehearse                     the whole loop with NO model: scripted answers (free)
    python lab/raphael/run.py paid --yes --hypothesis "…"  a real run (costs money; read `dry` first; ask the person first)
    python lab/raphael/run.py pick [--run DIR]             choose the small part for the post team to cut (free)
    python lab/raphael/run.py ledger                       every paid call so far and the total (free)

  stage 2, the cinematic pass (phase 0c/0d), from a FINISHED stage 1 run (no stage 1 call):
    python lab/raphael/run.py stage2 dry      [--from DIR]  what a paid pass would send and the most it could cost (free)
    python lab/raphael/run.py stage2 rehearse [--from DIR]  the whole pass with NO model: scripted answers (free)
    python lab/raphael/run.py stage2 paid --yes [--from DIR] --hypothesis "…"   a real pass (the person's yes first)
    python lab/raphael/run.py full --yes --past-read --hypothesis "…"           stage 1 (must only, S1) + stage 2, one run

Run it with `OPENAI__API_KEY=` blank for everything but `paid`: only `paid` reads `.env` and builds a client. The money rules
are DaVinci's code (davinci/money.py) with Raphael's OWN ledger: a run stops at $5.00 of model tokens and this lab never passes
$5.00 in all. Stop after 3 paid runs for the person's read (phase 0b). Stage 2 (phase 0d): at most 3 paid passes and $1.50
in all; a pass's cap is what its stage 1 run left of the $5.00 (the cap covers both stages of one scene).
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
from raphael import agent, rehearsal, rehearsal2, render, schema, stage2

LAB = Path(__file__).resolve().parent
RUNS = LAB / "runs"
LEDGER = RUNS / "ledger.csv"  # Raphael's own: the plan gives this lab its own $5
PAID_RUNS_BEFORE_READ = 3  # phase 0b: stop after three paid runs for the person's read
EXPECTED_TURNS = 8  # what `dry` quotes as a likely run; the caps are what is enforced
STAGE2_BUDGET_USD = 1.50  # phase 0d: every stage 2 pass in all
STAGE2_RUNS = 3  # phase 0d: then the person's read
STAGE2_EXPECTED_TURNS = 5
RUN3 = rehearsal2.RUN3  # phase 0d starts from run 3's bin (13 must, 70 s)


def config(args: argparse.Namespace) -> agent.Config:
    m = [*args.model.split(":"), "high"][:2]
    return agent.Config(model=(m[0], m[1]), max_output=args.max_output, max_turns=args.max_turns,
                        prompt=getattr(args, "prompt", "raphael"))


def config2(args: argparse.Namespace) -> agent.Config:
    m = [*args.model.split(":"), "high"][:2]
    return stage2.stage2_config(model=(m[0], m[1]), max_output=args.max_output, max_turns=args.max_turns)


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


# ── stage 2: the cinematic pass ──────────────────────────────────────────────────────────────────


def stage2_spent(meter: money.Meter) -> tuple[float, list[str]]:
    rows = [r for r in meter.rows() if r["slot"] == stage2.CinematicPass.SLOT]
    return sum(float(r["dollars"] or 0) for r in rows), sorted({r["run"] for r in rows})


def stage1_dollars(folder: Path) -> float:
    usage = folder / "usage.json"
    return float(json.loads(usage.read_text(encoding="utf-8")).get("run_dollars") or 0) if usage.is_file() else 0.0


def write_result2(folder: Path, reading: pack.Reading, cin: stage2.CinematicPass, out: agent.Outcome, meter: money.Meter,
                  source: str, origin: str, jonathan: dict[str, Any] | None) -> None:
    stage2.dump(folder, cin.work)
    n = cin.work.counts()
    changed = cin.changed_must()
    (folder / "outcome.json").write_text(json.dumps({
        "stage": 2, "from": origin, "stopped": out.stopped, "complete": out.finished, "turns": out.turns, "detail": out.detail,
        "blend_notes": out.editor_notes, "moment_review": cin.review, "cinematic": [e.id for e in stage2.extras(cin.work)],
        "changed_must": changed, "take_s": n["take_s"], "target_s": reading.guide_s, "cap_s": stage2.cap_s(reading),
        "faults": [f.model_dump() for f in out.faults]}, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "usage.json").write_text(json.dumps({"run_dollars": round(meter.spent, 4), "calls": meter.calls,
                                                   "run_cap": meter.run_cap}, indent=1), encoding="utf-8")
    if not out.finished:  # D1 (recommended): save it, marked incomplete; stage 1's bin is whole either way
        source = f"INCOMPLETE: the pass stopped ({out.stopped}) before `finish`; the must clips are stage 1's, whole. {source}"
    (folder / "bin.html").write_text(render.build_layers(reading, cin.work, out.faults, out.stopped, out.detail, source, jonathan,
                                                         out.turns, out.editor_notes, changed, cin.review),
                                       encoding="utf-8")


def summary2(out: agent.Outcome, cin: stage2.CinematicPass, meter: money.Meter, folder: Path) -> None:
    n = cin.work.counts()
    mine = stage2.extras(cin.work)
    print(f"{folder.name}: stage 2 {out.stopped} after {out.turns} turn(s). {out.detail}".strip())
    print(f"bin: {n['clips']} clips ({n['clips'] - len(mine)} must, {len(mine)} cinematic); {n['take_s']} s of takes "
          f"(cap {stage2.cap_s(cin.reading):g} s); must clips changed: {cin.changed_must() or 'none'}")
    for e in mine:
        print(f"  {e.id} [{e.slate}] moment {e.moment} {e.role} {e.technique} {e.take_s}s anchor {','.join(e.anchor)} "
              f"{e.blend}: {e.why}")
    blocking = checks.blocking(out.faults)
    print(f"faults: {len(blocking)} blocking, {len(out.faults) - len(blocking)} report(s)")
    for f in blocking:
        print("  " + f.line())
    print(f"model calls {meter.calls}, run ${meter.spent:.4f} of the ${meter.run_cap:.2f} cap; read {folder / 'bin.html'}")


def stage2_dry(reading: pack.Reading, work: Any, origin: Path, cfg: agent.Config) -> int:
    cin = stage2.CinematicPass(reading, work, rehearsal2.CinematicRehearsal(), money.Meter(RUNS / "dry.csv", "dry"),
                               RUNS / "dry", cfg)
    specs = cin.specs()
    first = tokens_of(cin.system + cin.opening + json.dumps(specs))
    print(f"=== prompt ({len(cin.system)} characters) ===\n{cin.system}\n")
    print(f"=== first message ({len(cin.opening)} characters) ===\n{cin.opening}\n")
    print("=== tools: " + ", ".join(s["name"] for s in specs) + f" ({len(json.dumps(specs))} characters of schemas)")
    model, effort = cfg.model
    if money.listed_price(model) is None:
        print(f"model {model} has no price in PRICES (cinematic/run.py): add it before a paid run.")
        return 1
    turn = money.worst_case(model, first, cfg.max_output)
    likely = sum(money.dollars(model, first + 6_000 * t, max(first + 6_000 * (t - 1), 0), 9_000)
                 for t in range(STAGE2_EXPECTED_TURNS))
    meter = money.Meter(LEDGER, "dry")
    spent, passes = stage2_spent(meter)
    print(f"from {origin.name} (stage 1 spent ${stage1_dollars(origin):.2f}); model {model} ({effort}), max_output "
          f"{cfg.max_output}, turn cap {cfg.max_turns}")
    print(f"first message about {first} tokens. WORST case of the first turn ${turn:.2f}")
    print(f"likely pass (about {STAGE2_EXPECTED_TURNS} turns, ~9k output each, cached input): ${likely:.2f}  [a guess]")
    print(f"stage 2 so far ${spent:.2f} of ${STAGE2_BUDGET_USD:.2f} in {len(passes)} of {STAGE2_RUNS} pass(es); lab "
          f"${meter.ledger_total():.2f} of ${money.LAB_BUDGET_USD:.2f}")
    print("A paid pass still needs the person's yes.")
    return 0


def cmd_stage2(args: argparse.Namespace) -> int:
    origin = Path(args.from_run) if args.from_run else RUN3
    reading = pack.load(davinci_run.scene_path(args.scene))
    cfg = config2(args)
    try:
        work = stage2.load_stage1(origin)  # refuses a stage 1 run that did not finish
    except ValueError as exc:
        raise money.LabError(str(exc)) from exc
    jonathan = davinci_run.jonathan_plan(args.jonathan)
    if args.mode == "dry":
        return stage2_dry(reading, work, origin, cfg)
    if args.mode == "rehearse":
        folder = RUNS / "rehearsal_stage2"
        if folder.exists():
            for f in folder.glob("*"):
                if f.is_file():
                    f.unlink()
        meter = money.Meter(folder / "pretend_ledger.csv", "rehearsal")  # pretend dollars, never the lab's ledger
        backend = rehearsal2.CinematicRehearsal()
        cin = stage2.CinematicPass(reading, work, backend, meter, folder, cfg)
        backend.bind(cin)
        out = cin.run()
        source = (f"REHEARSAL of stage 2: no model wrote the cinematic clips. They are scripted on {origin.name}'s real must bin "
                  "and run through the pass's real loop, tools and checks, so this page shows the SHAPE of the two layers, not "
                  "the quality of a model's. The dollars are pretend.")
        write_result2(folder, reading, cin, out, meter, source, origin.name, jonathan)
        summary2(out, cin, meter, folder)
        return 0 if out.finished and not checks.blocking(out.faults) and not cin.changed_must() else 1
    if not args.yes:
        print("A paid pass costs money. Read `stage2 dry` first, then run this again with --yes (and the person's yes).")
        return 2
    probe = money.Meter(LEDGER, "probe")
    spent, passes = stage2_spent(probe)
    if passes and not (args.hypothesis or "").strip():
        raise money.LabError("After the first pass, a pass needs --hypothesis: one change, one reason.")
    if len(passes) >= STAGE2_RUNS and not args.past_read:
        raise money.LabError(f"{len(passes)} stage 2 passes are done: phase 0d stops here for the person's read.")
    left = STAGE2_BUDGET_USD - spent
    if left <= 0:
        raise money.LabError(f"Stage 2 has spent ${spent:.2f} of its ${STAGE2_BUDGET_USD:.2f}: more is the person's decision.")
    folder = next_folder(f"stage2-{cfg.model[0]}_{cfg.model[1]}-from{origin.name.split('-')[0]}")
    meter = money.Meter(LEDGER, folder.name, run_cap=max(money.RUN_CAP_USD - stage1_dollars(origin), 0.0),
                        lab_budget=min(money.LAB_BUDGET_USD, probe.ledger_total() + left),
                        hypothesis=args.hypothesis or "(the first pass)")
    from cinematic.run import client  # the only place the lab builds a client, and it reads .env
    from davinci.brain import OpenAIBackend

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.md").write_text(f"# Stage 2 pass {folder.name}\n\nFrom {origin.name}. Hypothesis: "
                                     f"{args.hypothesis or '(the first pass)'}\n\nModel {cfg.model}, max_output "
                                     f"{cfg.max_output}, turn cap {cfg.max_turns}.\n", encoding="utf-8")
    cin = stage2.CinematicPass(reading, work, OpenAIBackend(client()), meter, folder, cfg)
    out = cin.run()
    write_result2(folder, reading, cin, out, meter, f"A real stage 2 pass: {cfg.model[0]} ({cfg.model[1]}) on {origin.name}'s "
                  f"must bin. Model tokens ${meter.spent:.2f}.", origin.name, jonathan)
    summary2(out, cin, meter, folder)
    return 0 if out.finished else 1


def cmd_full(args: argparse.Namespace) -> int:
    """Phase 0d's last step: stage 1 with the must-only prompt (S1), then stage 2 on its bin, under ONE $5 run cap."""
    if not args.yes:
        print("A full run costs money (both stages). Read `dry --prompt raphael_must` and `stage2 dry` first, then --yes.")
        return 2
    if not (args.hypothesis or "").strip():
        raise money.LabError("A full run needs --hypothesis: one change, one reason.")
    done = paid_runs()
    if len(done) >= PAID_RUNS_BEFORE_READ and not args.past_read:
        raise money.LabError(f"{len(done)} paid runs are done: a full run comes after the person's read (--past-read).")
    reading = pack.load(davinci_run.scene_path(args.scene))
    cfg1 = config(args)
    cfg2 = config2(argparse.Namespace(model=args.model, max_output=args.max_output, max_turns=args.stage2_max_turns))
    folder = next_folder(f"full-{cfg1.model[0]}_{cfg1.model[1]}-{args.scene}")
    meter = money.Meter(LEDGER, folder.name, hypothesis=args.hypothesis)  # ONE meter: the $5 cap covers both stages
    from cinematic.run import client
    from davinci.brain import OpenAIBackend

    backend = OpenAIBackend(client())
    one = folder / "stage1"
    one.mkdir(parents=True, exist_ok=True)
    (folder / "notes.md").write_text(f"# Full run {folder.name}\n\nHypothesis: {args.hypothesis}\n\nStage 1 prompt "
                                     f"{cfg1.prompt}, model {cfg1.model}, turns {cfg1.max_turns}; stage 2 turns "
                                     f"{cfg2.max_turns}.\n", encoding="utf-8")
    jonathan = davinci_run.jonathan_plan(args.jonathan)
    raph = agent.Raphael(reading, backend, meter, one, cfg1)
    out1 = raph.run()
    write_result(one, reading, raph, out1, meter, f"A real run, stage 1 ({cfg1.prompt}): {cfg1.model[0]}.", jonathan)
    summary(out1, raph, meter, one)
    if not out1.finished:
        print("Stage 1 did not finish: stage 2 is not run (it adds to a finished must bin only).")
        return 1
    cin = stage2.CinematicPass(reading, stage2.load_stage1(one), backend, meter, folder, cfg2)
    out2 = cin.run()
    write_result2(folder, reading, cin, out2, meter, f"A real full run: {cfg1.model[0]} ({cfg1.model[1]}), stage 1 then "
                  f"stage 2. Model tokens ${meter.spent:.2f} for both.", one.name, jonathan)
    summary2(out2, cin, meter, folder)
    return 0 if out2.finished else 1


BLEND_ORDER = ("cut_in", "under_line", "close", "open", "transition")


def cmd_pick(args: argparse.Namespace) -> int:
    """DaVinci's small part (three angles, a transition pair, a drone or B-roll clip) and, from a two-layer bin, ONE cinematic
    clip with its anchor(s), so the post team can try blending it in."""
    folder = Path(args.run) if args.run else RUNS / "rehearsal"
    code = davinci_run.cmd_pick(argparse.Namespace(run=str(folder)))
    clips = json.loads((folder / "bin.json").read_text(encoding="utf-8"))
    cin = sorted((c for c in clips if c.get("stage") == 2 and c.get("ir")),
                 key=lambda c: (BLEND_ORDER.index(c["blend"]) if c.get("blend") in BLEND_ORDER else 9, c["id"]))
    if not cin:
        return code
    chosen = cin[0]
    by_id = {c["id"]: c for c in clips}
    out = folder / "post_test"
    lines = ["", "## One cinematic clip and its anchor (stage 2)", ""]
    keep = ("id", "slate", "role", "technique", "take_s", "handle_in_s", "handle_out_s", "lines", "speaks", "ir", "sound",
            "stage", "anchor", "blend")
    for c in [chosen, *(by_id[a] for a in chosen.get("anchor") or [] if a in by_id)]:
        name = re.sub(r"[^A-Za-z0-9]+", "_", c["slate"])
        (out / f"{name}.json").write_text(json.dumps({k: c[k] for k in keep if k in c}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        tag = f"cinematic, {c['blend']} with {', '.join(c['anchor'])}" if c.get("stage") == 2 else "its anchor (must)"
        lines.append(f"- **{c['slate']}** ({c['id']}, {tag}): {c['role']}, {c['size']}, {c['technique']}, {c['take_s']} s; "
                     f"{c['why']}  → `post_test/{name}.json`")
    lines += ["", "6. Does the cinematic clip blend in at its anchor as its blend says (light, wardrobe, place)? Would you use it?"]
    with (folder / "post_test.md").open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return code


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
        p.add_argument("--prompt", default="raphael", choices=("raphael", "raphael_must"),
                       help="stage 1's prompt: raphael (runs 1-3) or raphael_must (S1: must clips only)")
        if name == "paid":
            p.add_argument("--yes", action="store_true")
            p.add_argument("--hypothesis", default="")
            p.add_argument("--past-read", action="store_true", help="a fourth run or later: only after the person's read")
    p = sub.add_parser("stage2", help="the cinematic pass on a finished stage 1 run")
    p.set_defaults(fn=cmd_stage2)
    p.add_argument("mode", choices=("dry", "rehearse", "paid"))
    p.add_argument("--from", dest="from_run", default="", help="a finished stage 1 run folder (default: run 3)")
    p.add_argument("--scene", default="episode1")
    p.add_argument("--model", default="gpt-5:high", help="S4: the same model as stage 1")
    p.add_argument("--max-output", type=int, default=48_000)
    p.add_argument("--max-turns", type=int, default=12, help="S4")
    p.add_argument("--jonathan", default="")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--hypothesis", default="")
    p.add_argument("--past-read", action="store_true", help="a fourth pass or later: only after the person's read")
    p = sub.add_parser("full", help="stage 1 (must only, S1) then stage 2, one run under one cap")
    p.set_defaults(fn=cmd_full)
    p.add_argument("--scene", default="episode1")
    p.add_argument("--model", default="gpt-5:high")
    p.add_argument("--max-output", type=int, default=48_000)
    p.add_argument("--max-turns", type=int, default=20)
    p.add_argument("--stage2-max-turns", type=int, default=12)
    p.add_argument("--prompt", default="raphael_must", choices=("raphael", "raphael_must"))
    p.add_argument("--jonathan", default="")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--hypothesis", default="")
    p.add_argument("--past-read", action="store_true")
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
