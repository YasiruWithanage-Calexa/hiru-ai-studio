"""Shot Planner Adam on the gold scenes with the REAL model (plan/2026-11-04b §10): what only a live run can show.

    python scripts/adam_live.py --yes                         # every gold scene
    python scripts/adam_live.py --yes --scene phone_call      # one
    python scripts/adam_live.py --yes --no-screening          # without the four critics and the revision

It refuses to start without `--yes`: a scene is about eleven model calls and they cost money. Nothing is written to a
database (the planner needs none); each plan is saved under `tests/eval/adam/live/<scene>.json` and a table says, per
scene, the craft score of the first plan and the final one, whether the revision after screening won, the fidelity
breaks and the overruns. Those are the numbers the Phase 3 to 5 exits ask for ("the revised plan wins on score in at
least 60% of gold scenes and never loses fidelity"); whether the treatments are a real director's ideas and whether
the cards read like section 9 is a person's judgement, so the plans are saved for a person to read and for `adam_ab.py`.
Run it with the key in `.env` (OPENAI__API_KEY); the models are the configured tiers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "libs"))
sys.path.insert(0, str(ROOT))

LIVE = ROOT / "tests" / "eval" / "adam" / "live"
WINS_TARGET = 0.60


def run_scene(name: str, screening: bool) -> dict[str, object]:
    from tests.adam import gold, stages

    from contracts.adam.plan import SceneScript
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.adam.adam_shot_planner.scene import Planner

    script = SceneScript.model_validate(gold.scene(name))
    line_ids = {b.line_id: b.line_id for b in script.lines if b.line_id}
    planner = Planner(RunContext(), script, context={"heading": stages.title(name)}, line_ids=line_ids, removed=[],
                      screening=screening)
    planned = planner.plan()
    report = planned.stored.report
    LIVE.mkdir(parents=True, exist_ok=True)
    saved = json.dumps(planned.stored.data(), ensure_ascii=False, indent=2)
    (LIVE / f"{name}.json").write_text(saved, encoding="utf-8")
    return {"scene": name, "percent": (report.get("score") or {}).get("percent"),
            "kept": (report.get("screening") or {}).get("kept", ""),
            "breaks": (report.get("fidelity") or {}).get("counts", {}).get("breaks"),
            "overruns": (report.get("fit") or {}).get("overruns"), "cards": len(planned.stored.cards),
            "seconds": (report.get("fit") or {}).get("runtime_s")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="yes, spend the model calls")
    parser.add_argument("--scene", action="append", help="a gold scene (default: all)")
    parser.add_argument("--no-screening", action="store_true")
    args = parser.parse_args(argv)
    if not args.yes:
        print("This calls the real model about eleven times per scene. Run again with --yes to go ahead.")
        return 2
    from tests.adam import gold

    names = args.scene or gold.names()
    rows = []
    for name in names:
        try:
            rows.append(run_scene(name, not args.no_screening))
        except Exception as exc:  # a scene Adam cannot plan is a result, not a crash
            rows.append({"scene": name, "error": f"{type(exc).__name__}: {exc}"[:160]})
        print(rows[-1], flush=True)
    revised = [r for r in rows if r.get("kept")]
    won = sum(r["kept"] == "revision" for r in revised)
    broke = sum(bool(r.get("breaks")) for r in rows)
    print(f"\n{len(rows)} scenes; the revision won on {won} of {len(revised)} "
          f"(target {WINS_TARGET:.0%}); {broke} with a fidelity break (target 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
