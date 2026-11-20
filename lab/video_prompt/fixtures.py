"""Save E01-S04 as the product's `video_prompt` step reads it (plan/2026-11-20b phase 2): free, nothing is sent.

    .venv/Scripts/python.exe lab/video_prompt/fixtures.py

The scene packet, each clip's facts (`steps/video_prompt/facts.clip_facts` on the lab's world: the coverage lab's rows
and Raphael's saved run) and run 003's sol answers, into the step's `tests/fixtures/e01_s04.json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src"), str(ROOT / "lab"), str(HERE)]
OUT = ROOT / "src" / "libs" / "hiru_ai" / "steps" / "video_prompt" / "tests" / "fixtures" / "e01_s04.json"


def main() -> None:
    import run as lab  # lab/video_prompt/run.py

    from hiru_ai.steps.video_prompt import facts

    world = lab.load()
    scene, packet = world["scene"], world["packet"]
    scene.row = {**scene.row, "raphael": json.loads(lab.SAVED.read_text(encoding="utf-8"))["result"]}
    lids = facts.line_ids_for(packet, world["lines"])
    assert lids is not None
    clips, answers = {}, {}
    for shot in sorted(scene.shots, key=lambda s: s.number):
        slate = str(shot.row.get("slate"))
        clips[slate] = facts.clip_facts(shot, scene, world["prod"], {"id": "frame-1"}, lids=lids)
        ans = HERE / "runs" / "003_gpt-6.1-sol" / "answers" / f"{slate}.json"
        if ans.exists():
            answers[slate] = json.loads(ans.read_text(encoding="utf-8"))["direction"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"packet": packet, "clips": clips, "answers": answers}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"{len(clips)} clips, {len(answers)} answers -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
