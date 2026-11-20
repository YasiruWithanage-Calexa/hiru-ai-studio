"""E01-S04 as plan/2026-11-20 planned it in line parts (lab/line_parts/runs/003_product: the product's Raphael, live),
read the way the product's `video_prompt` step reads it: free, nothing is sent.

    .venv/Scripts/python.exe lab/video_prompt/parts_world.py      prints each clip's lines as the brief names them

`live_product.py --parts` writes these clips' prompts with the product's agent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab"), str(HERE)]
RUN = ROOT / "lab" / "line_parts" / "runs" / "003_product"


def parts_data() -> dict[str, Any]:
    import run as lab  # lab/video_prompt/run.py

    from hiru_ai.steps.serialize.model import production_input, scene_input
    from hiru_ai.steps.video_prompt import facts

    cov = lab.coverage_lab()
    w = cov.world()
    stored = json.loads((RUN / "result.json").read_text(encoding="utf-8"))
    assert stored.get("line_parts"), "run 003 was not planned in parts"
    w["scene"] = {**w["scene"], "line_parts": True}
    rows, lines = cov.shot_rows(w, stored)  # raphael_write, as the product writes it
    prod = production_input(w["production"], w["canon"], None)
    scene = scene_input({**w["scene"], "raphael": stored}, rows, lines, w["canon"], prod)
    lids = facts.line_ids_for(w["packet"], lines)
    assert lids is not None, "packet and line rows differ"
    clips = {str(s.row.get("slate")): facts.clip_facts(s, scene, prod, {"id": "frame-1"}, lids=lids)
             for s in sorted(scene.shots, key=lambda s: s.number)}
    return {"packet": w["packet"], "clips": clips}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    data = parts_data()
    for slate, c in data["clips"].items():
        said = [f"{ln['lid']}{f' ({ln['part']}/{ln['parts']})' if ln.get('parts') else ''}" for ln in c["lines"]]
        print(f"{slate:5} {c['sound_mode']:9} {c['take_s']:>4} s  lines {said}  edit {c['edit_lines']}")


if __name__ == "__main__":
    main()
