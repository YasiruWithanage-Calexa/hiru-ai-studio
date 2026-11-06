"""The live trial of Shot Planner Jonathan (plan/2026-11-06b §7 phase 6, §8 the gate): the real planner, the author and
the stabiliser, on scenes from files, repeated, with a hard budget.

    python scripts/jonathan_spike.py --yes                              # the gold scenes, once each
    python scripts/jonathan_spike.py --yes --repeat 3                   # the gate: every scene three times
    python scripts/jonathan_spike.py --yes --scene phone_call           # one gold scene
    python scripts/jonathan_spike.py --yes --scene-file lab/cinematic/input/reading.yaml   # a scene in the lab's shape
    python scripts/jonathan_spike.py --yes --budget 2.50                # stop before the spend could pass $2.50

It refuses to start without `--yes`: every scene is one to three calls of the author's model at high effort (the lab:
$0.18 to $0.58 a scene on gpt-5), and that costs money. A person starts it (the plan's rule) and reads what it writes.
No new scene starts once the spend so far plus one scene's worst case (`SCENE_WORST_USD`) would pass `--budget`.

A scene file is either a gold scene (`tests/eval/jonathan/scenes/*.yaml`: `scene:` with cast, place and blocks) or the
lab's shape, which adds `people` (name, code, look, voice, essence), `style`, `heading`, `synopsis`, `time.guide_s` and
`story_objects`. What a gold scene lacks is left out of the pack, as the product leaves out what the database lacks.

For each run it saves the stored plan (`tests/eval/jonathan/spike/<scene>/<n>.json`, with the treatment, the measures
and every revise pass) and its model calls (`<n>.usage.json`), and writes `spike/summary.md`: per run the calls, the
draft's score and the final score (faults, craft gaps), the shots, the seconds taken and kept, the cost and the time;
per scene whether the gate's points 1 and 3 hold (zero faults in every run; clean within three calls). Nothing is
written to a database, and no number here is made up: a run that did not finish is said aloud and left out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

EVAL = ROOT / "tests" / "eval" / "jonathan"
SPIKE = EVAL / "spike"
EXAMPLE_SCENE = "refuses_money"  # the scene the author's prompt shows: the model has seen that answer, so it is not run
SCENE_WORST_USD = 0.75  # one scene's worst case: three calls at the most the lab saw one cost (gpt-5 high), with room
# model -> (input, cached input, output), US dollars per million tokens: OpenAI's list prices on the standard tier. An
# exact name or a dated snapshot of it only (the lab found that a prefix match billed gpt-5.5 as gpt-5).
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5.5": (5.00, 0.50, 30.00)}
Row = dict[str, Any]


def price_of(model: str) -> tuple[float, float, float]:
    name = model.lower()
    for known, price in PRICES.items():
        if name == known or (name.startswith(known + "-") and name[len(known) + 1:][:1].isdigit()):
            return price
    raise ValueError(f"No price for {model!r}: add it to PRICES from OpenAI's pricing page first.")


def cost(row: Row) -> float:
    """US dollars one `token_usage` row cost. An output token includes the hidden reasoning."""
    pin, pcached, pout = price_of(str(row.get("model") or "gpt-5"))
    prompt, cached = int(row.get("input_tokens") or 0), int(row.get("cached_input_tokens") or 0)
    return (max(prompt - cached, 0) * pin + cached * pcached + int(row.get("output_tokens") or 0) * pout) / 1_000_000


def gold_names() -> list[str]:
    return sorted(p.stem for p in (EVAL / "scenes").glob("*.yaml") if p.stem != EXAMPLE_SCENE)


def load_scene(path: Path) -> tuple[str, Any, Row, Any]:
    """-> (its name, the scene as Jonathan is given it, the pack data, the craft facts)."""
    from contracts import sceneplan
    from contracts.jonathan.measures import Craft
    from contracts.jonathan.scene import BlockS, PlaceS, SceneS, plain_name
    from contracts.shotplan import Item

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    sc = raw["scene"]
    items = sceneplan._read_unread([Item(b["index"], b["kind"], b["text"], b.get("speaker", ""), None,
                                         b.get("delivery", ""), b.get("line_id")) for b in sc["blocks"]])
    guide = float((raw.get("time") or {}).get("guide_s") or sc.get("envelope_s") or 0) or None
    # and every speaker the cast does not list (a voice on the phone), as the product's `present` does
    cast = list(sc["cast"])
    cast += list(dict.fromkeys(plain_name(i.speaker) for i in items if i.speaker and plain_name(i.speaker) not in cast))
    scene = SceneS(blocks=[BlockS.of(i) for i in items], cast=cast, others=list(sc.get("others") or []),
                   place=PlaceS(name=sc["place"]["name"], objects=list(sc["place"]["objects"])), envelope_s=guide)
    people = list(raw.get("people") or [{"name": n, "code": f"C{i:02d}"} for i, n in enumerate(scene.cast, start=1)])
    pack = {"production": {"style_note": str(raw.get("style") or ""),
                           "people": [{k: str(p.get(k) or "") for k in ("name", "code", "look", "voice", "essence")}
                                      for p in people]},
            "context": {"heading": str(raw.get("heading") or raw.get("title") or path.stem),
                        "episode_title": str(raw.get("episode_title") or ""),
                        "synopsis": " ".join(str(raw.get("synopsis") or "").split())}}
    craft = Craft(codes={str(p["name"]): str(p.get("code") or "") for p in people},
                  story_objects=[str(o) for o in raw.get("story_objects") or []], guide_s=float(guide or 0))
    return str(raw.get("id") or path.stem), scene, pack, craft


def run_one(path: Path, n: int) -> Row:
    """One scene through the planner once; the row the table is made from."""
    from contracts.jonathan.stored import Link
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.jonathan.jonathan_shot_planner.scene import Planner

    name, scene, pack, craft = load_scene(path)
    usage: list[Row] = []
    line_ids = {b.line_id: b.line_id for b in scene.lines if b.line_id}
    planner = Planner(RunContext(usage_sink=usage.append, usage_detail=True), scene, number=1, line_ids=line_ids,
                      pack=pack, removed=[], link=Link(), start=None, before=None, craft=craft)
    started = time.monotonic()
    planned = planner.plan(previous={}, job_id="spike")
    seconds = time.monotonic() - started
    folder = SPIKE / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{n}.json").write_text(json.dumps(planned.stored.data(), ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{n}.usage.json").write_text(json.dumps(usage, ensure_ascii=False, indent=1), encoding="utf-8")
    stored = planned.stored
    row = {"scene": name, "run": n, "calls": len(usage), "revises": planner.calls["revise"],
           "first": list(stored.report.get("first_score") or []), "score": list(stored.report.get("score") or []),
           "shots": len(stored.plan.shots), "take_s": sum(s.take_s for s in stored.plan.shots),
           "use_s": sum(s.use_s for s in stored.plan.shots), "guide_s": craft.guide_s, "seconds": round(seconds, 1),
           "reasoning": sum(int(r.get("reasoning_tokens") or 0) for r in usage),
           "dollars": round(sum(cost(r) for r in usage), 4)}
    print(f"\n{name} run {n}: {row['calls']} calls, draft {row['first']} -> {row['score']}, {row['shots']} shots, "
          f"{row['use_s']} s kept, ${row['dollars']}, {row['seconds']} s", flush=True)
    return row


def summary(rows: list[Row]) -> str:
    """The table, and the gate's points 1 and 3 per scene: a scene with no finished run has no row."""
    head = ("| Scene | Run | Calls | Draft (faults, gaps) | Final | Shots | Takes s | Kept s (guide) | $ | Seconds |\n"
            "|---|---|---|---|---|---|---|---|---|---|")
    lines = [f"| {r['scene']} | {r['run']} | {r['calls']} | {tuple(r['first'])} | {tuple(r['score'])} | {r['shots']} | "
             f"{r['take_s']} | {r['use_s']} ({r['guide_s']:g}) | {r['dollars']:.2f} | {r['seconds']:.0f} |"
             for r in rows]
    gate = ["", "| Scene | Runs | Zero faults in every run (gate 1) | Clean within 3 calls (gate 3) |",
            "|---|---|---|---|"]
    for name in dict.fromkeys(r["scene"] for r in rows):
        mine = [r for r in rows if r["scene"] == name]
        zero = all(r["score"] and r["score"][0] == 0 for r in mine)
        clean = sum(1 for r in mine if r["score"] and r["score"][0] == 0 and r["calls"] <= 3)
        gate.append(f"| {name} | {len(mine)} | {'yes' if zero else 'no'} | {clean} of {len(mine)} |")
    spent = sum(r["dollars"] for r in rows)
    return head + "\n" + "\n".join(lines) + "\n" + "\n".join(gate) + f"\n\nSpent: ${spent:.2f}.\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--yes", action="store_true", help="really call the model (it costs money)")
    ap.add_argument("--scene", action="append", help="a gold scene by name (default: the gold scenes)")
    ap.add_argument("--scene-file", action="append", help="a scene yaml (a gold scene or the lab's shape)")
    ap.add_argument("--repeat", type=int, default=1, help="runs per scene (the gate asks for 3)")
    ap.add_argument("--budget", type=float, default=3.00, help="US dollars: no scene starts that could pass it")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.scene_file or []]
    paths += [EVAL / "scenes" / f"{n}.yaml" for n in (args.scene or ([] if paths else gold_names()))]
    if not args.yes:
        worst = len(paths) * args.repeat * SCENE_WORST_USD
        print(f"This calls the real model one to three times per scene and run: {len(paths)} scene(s) x {args.repeat} "
              f"run(s), at worst about ${worst:.2f}, never more than --budget (${args.budget:.2f}). Run it again with "
              "--yes to start it.")
        return 2
    from _common import load_env

    load_env()
    from hiru_ai.core.telemetry import enable_tracing

    print("Langfuse tracing:", "on" if enable_tracing() else "off (no LANGFUSE_ keys)")
    rows: list[Row] = []
    for path in paths:
        for n in range(1, args.repeat + 1):
            spent = sum(r["dollars"] for r in rows)
            if spent + SCENE_WORST_USD > args.budget:
                print(f"\nStopped before {path.stem} run {n}: ${spent:.2f} spent, and one more scene could pass the "
                      f"${args.budget:.2f} budget.", flush=True)
                break
            try:
                rows.append(run_one(path, n))
            except Exception as exc:  # a run that could not finish is a row left out, said aloud
                print(f"\n{path.stem} run {n}: did not finish ({type(exc).__name__}: {exc})", flush=True)
    SPIKE.mkdir(parents=True, exist_ok=True)
    table = summary(rows)
    (SPIKE / "summary.md").write_text(table, encoding="utf-8")
    print("\n" + table)
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
