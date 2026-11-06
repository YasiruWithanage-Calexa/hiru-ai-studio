"""Writes Zora's offline fixtures (plan/2026-11-06e Phase 0) from the cinematic lab's saved runs: no model call.

    tests/eval/zora/fixtures/<scene>.json   {"scene": the scene as the planner is given it, "plan": the mended plan}

The lab's run folders are not in git (`lab/cinematic/.gitignore`), so the plans the tests read are copied out here once.
Run `python lab/zora/build_fixtures.py` from the repository root.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT)]

from lab.cinematic.pack import load  # noqa: E402

RUNS = ROOT / "lab" / "cinematic" / "runs"
GOLD = ROOT / "tests" / "eval" / "jonathan" / "scenes"
OUT = ROOT / "tests" / "eval" / "zora" / "fixtures"
# scene → (its input file, the lab run whose mended plan is the scene's plan)
SOURCES = {
    "episode1": (ROOT / "lab" / "cinematic" / "input" / "reading.yaml", "14-gpt_5-high"),
    "arrival": (GOLD / "arrival.yaml", "15-gpt_5-high-arrival"),
    "father_refuses": (GOLD / "father_refuses.yaml", "16-gpt_5-high-father_refuses"),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (source, run) in SOURCES.items():
        reading = load(source)
        plan = json.loads((RUNS / run / "plan_mended.json").read_text(encoding="utf-8"))
        body = {"name": name, "run": run, "scene": reading.scene.model_dump(mode="json"), "plan": plan}
        (OUT / f"{name}.json").write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{name}: {len(plan['shots'])} shots from {run}")


if __name__ == "__main__":
    main()
