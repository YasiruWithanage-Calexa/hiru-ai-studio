"""Implied-phone lab: Raphael (both stages, packet path) on one saved packet, with a chosen length cap and, optionally,
one extra prompt line added to the planner and cinematic system prompts IN THIS PROCESS ONLY (product files untouched).
No database. Paid: run only with the person's yes. Each run under Raphael's own meter (RAPHAEL_SCENE_CAP_USD, $1.00).

    python lab/implied_phone/run.py <packet dir> <out dir> --cap 1 [--line]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src" / "libs"), str(ROOT / "src" / "services"), str(ROOT / "lab" / "two_memories")]

LINE = (
    "\n\n- IMPLIED DEVICE (lab 2026-11-12). A thing marked (inferred) that a block names as its device (a phone, a "
    "radio) is part of the scene, as real as a scripted prop: showing it is not invention, and neither is the one small "
    "action that starts it. A voice heard through a device starts only after its source is shown. Plan a close-up of "
    "the device on the beat the voice begins: a live call, the screen lights up with the caller's name and it buzzes; "
    "a voice message or recording, the screen lights with the sender's name as the message starts, or one thumb press "
    "starts it. That close-up is a must clip, one per call or message, not a cinematic extra."
)
PATCHED = ("raphael_planner", "raphael_cinematic")


def house_block(path: Path) -> str:
    """A house rule file (header, ---, text) as the planned `house_rules` middleware would append it to the system prompt."""
    head, _, body = path.read_text(encoding="utf-8").partition("---")
    rid = next(x.split(":", 1)[1].strip() for x in head.splitlines() if x.startswith("id:"))
    kind = next(x.split(":", 1)[1].strip() for x in head.splitlines() if x.startswith("kind:"))
    return (
        "\n\nHOUSE RULES (the studio's own rules, given to every planner; a `default` rule yields to the production's "
        f"direction, a `must` rule never does)\n- {rid} ({kind}) {body.strip()}"
    )


def patch_prompts() -> None:
    from hiru_ai.core import prompts

    original = prompts.Prompt.load.__func__  # type: ignore[attr-defined]

    def load(cls, path: Path):  # type: ignore[no-untyped-def]
        p = original(cls, path)
        if any(part in PATCHED for part in Path(path).parts) and Path(path).name == "system.md":
            print(f"  + lab line added to {Path(path).parent.parent.name}", flush=True)
            return prompts.Prompt(name=p.name, text=p.text + LINE)
        return p

    prompts.Prompt.load = classmethod(load)  # type: ignore[method-assign]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packets")
    ap.add_argument("out")
    ap.add_argument("--cap", type=float, required=True)
    ap.add_argument("--line", action="store_true")
    ap.add_argument("--rule", default="", help="a house rule file, appended instead of the lab line")
    a = ap.parse_args()
    if a.rule:
        global LINE
        LINE = house_block(Path(a.rule))
        a.line = True
    if a.line:
        patch_prompts()
    from contracts.raphael.packet import opening
    from hiru_ai.core.context import RunContext
    from hiru_ai.systems.raphael.raphael_shot_planner import scene as raphael
    from live import clip_text  # lab/two_memories/live.py

    packets = json.loads((Path(a.packets) / "09_packets.json").read_text(encoding="utf-8"))
    out = Path(a.out)
    (out / "12_raphael").mkdir(parents=True, exist_ok=True)
    for sid, p in packets.items():
        text, script, ids = opening(p)
        line_ids = {k: v for k, v in ids.items() if k.startswith("L")}
        planner = raphael.Planner(
            RunContext(), script, number=2, line_ids=line_ids, production={}, context={}, opening=text, cap=a.cap
        )
        t0 = time.monotonic()
        try:
            result, status = planner.plan(previous={}, job_id=f"lab-{sid}").stored.model_dump(mode="json"), "done"
        except raphael.Failed as exc:
            result, status = {}, f"failed: {exc}"
        summary = {"scene": sid, "cap": a.cap, "line": a.line, "status": status, "seconds": round(time.monotonic() - t0),
                   "calls": planner.meter.calls, "dollars": round(planner.meter.spent, 4), "log": planner.log}
        (out / "12_raphael" / f"{sid}.json").write_text(
            json.dumps({**summary, "ids": ids, "result": result}, indent=1, ensure_ascii=False), encoding="utf-8")
        (out / "12_raphael" / f"{sid}.txt").write_text(clip_text(sid, result, p, ids, status), encoding="utf-8")
        print(f"{out.name}: {status}, cap {a.cap}, line {a.line}, {planner.meter.calls} calls, "
              f"{summary['seconds']} s, ${planner.meter.spent:.4f}", flush=True)


if __name__ == "__main__":
    main()
