"""Zora on the shot rows: the lab (plan/2026-11-12d phase 0). NOTHING is written to the database or to `src/`.

    python lab/zora_rows/run.py rehearse              # the whole scenario with NO model (canned answers): runs/rehearsal
    python lab/zora_rows/run.py dry                   # what the paid run would send, and its worst case
    python lab/zora_rows/run.py paid --yes [--run NAME]   # PAID: the person's yes first

The scenario is twelve turns of one thread on Hiru Short Combined 2, Scene 03 (Colombo garage, planned by Raphael): a
question, an exact change, a craft note, a risky removal accepted then undone, a risky removal rejected, a script change
(not possible here), an insert, options and "Use this". Results: runs/<run>/turns.json, rows_after.json, index.html.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "src" / "libs"), str(ROOT / "lab")]

import agents  # noqa: E402
import render  # noqa: E402
from coverage import Coverage  # noqa: E402
from turn import Thread, run_turn  # noqa: E402

SCENE = HERE / "input" / "0f4ba0fd-db0b-4722-8feb-e89586b06f24.json"
SCENARIO = [
    ("t01", "Why is S01 only a medium shot? It's the first image of the flashback."),
    ("t02", "Make S01 a wide, 6 seconds."),
    ("t03", "The argument from S08 to S13 drags. Make it tenser."),
    ("t04", "Drop S08."),
    ("t05", "[Accept]"),
    ("t06", "Undo that."),
    ("t07", "Remove S05, we don't need the master there."),
    ("t08", "[Reject]"),
    ("t09", "Change Nimal's line in S11 to say 400 million."),
    ("t10", "Add a close-up insert of the key in Dinu's palm after S15."),
    ("t11", "Give me two ways to end the scene."),
    ("t12", "[Use 1]"),
]

_NUL = {"shot": None, "field": None, "value": None, "take_s": None, "role": None, "priority": None, "after": None,
        "first_block": None, "last_block": None, "who": None, "what": None, "at_block": None, "to_shot": None,
        "line": None}


def _op(**kw: object) -> dict:
    return {**_NUL, **kw}


def _c(lane: str, ops: list | None = None, tasks: list | None = None, **kw: object) -> dict:
    return {"lane": lane, "confidence": 0.9, "ops": ops or [], "tasks": tasks or [], "variants": kw.get("variants", 0),
            "cannot": kw.get("cannot"), "memory": ""}


_PICTURE = json.dumps([{"time": "0-4s", "action": "The C-17 key rests in Dinu's open palm; his fingers close slowly.",
                        "camera": "INSERT, locked off, shallow focus", "performance": "The hand hesitates before it "
                        "closes.", "director_line": "The choice, in a hand."}])
REHEARSAL = {
    "t01.conductor": _c("chat"),
    "t01.reply_small": "S01 holds the two men in one restrained frame: the flashback opens on their private deal, not the place.",
    "t02.conductor": _c("edit", [_op(op="set", shot="S01", field="size", value="WIDE"), _op(op="retime", shot="S01",
                                                                                           take_s=6)]),
    "t03.conductor": _c("craft", tasks=[{"writes": ["camera", "timing"], "shots": [8, 9, 10, 11, 12, 13],
                                         "instruction": "make the argument tenser"}]),
    "t03.author": {"notes": "Closer at the turn and shorter reaction holds.", "asks": [], "variants": [],
                   "ops": [_op(op="set", shot="S09", field="size", value="CU"), _op(op="retime", shot="S10", take_s=4),
                           _op(op="set", shot="S02", field="size", value="CU")]},
    "t04.conductor": _c("edit", [_op(op="remove", shot="S08")]),
    "t07.conductor": _c("edit", [_op(op="remove", shot="S05")]),
    "t09.conductor": _c("cannot", cannot={"reason": "A line's words are the script's.", "route": "the script card"}),
    "t10.conductor": _c("edit", [_op(op="insert", after="S15", role="insert", size="INSERT", take_s=4, first_block=5,
                                     last_block=5, who=["Dinu"], what="the key in Dinu's palm")]),
    "t10.author": {"notes": "The new insert lands the key in Dinu's palm.", "asks": [], "variants": [],
                   "ops": [_op(op="set", shot="S16", field="why", value="The weight of the choice lands in one palm."),
                           _op(op="set", shot="S16", field="beats", value=_PICTURE),
                           _op(op="set", shot="S16", field="lighting", value="The greenish overhead practical.")]},
    "t11.conductor": _c("options", tasks=[{"writes": ["camera", "timing", "order"], "shots": [18, 19, 20, 21],
                                           "instruction": "two ways to end the scene"}], variants=2),
    "t11.author": {"notes": "", "asks": [], "ops": [], "variants": [
        {"label": "Hold on Dinu", "ops": [_op(op="retime", shot="S18", take_s=8)]},
        {"label": "End on the two of them", "ops": [_op(op="set", shot="S19", field="size", value="WIDE")]}]},
}


def run(backend: object, name: str) -> Path:
    out = agents.RUNS / name
    out.mkdir(parents=True, exist_ok=True)
    th = Thread(cov=Coverage.load(SCENE))
    start = th.cov.copy()
    records = []
    for slot, message in SCENARIO:
        print(f"{slot}: {message}", flush=True)
        try:
            rec = run_turn(th, message, backend, slot)
        except agents.CapError as exc:
            print(f"STOPPED: {exc}")
            records.append({"slot": slot, "message": message, "stopped": str(exc)})
            break
        records.append(rec)
        print(f"  lane {rec['lane']} · saved {rec['saved']} · card {bool(rec['card'])} · ${rec['dollars']:.4f}")
    (out / "turns.json").write_text(json.dumps(records, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (out / "rows_after.json").write_text(json.dumps(th.cov.to_rows(), indent=1, ensure_ascii=False, default=str),
                                         encoding="utf-8")
    spent = sum(r.get("dollars", 0) for r in records)
    (out / "index.html").write_text(render.page(name, start, th.cov, records, spent), encoding="utf-8")
    print(f"{name}: {len(records)} turns, ${spent:.4f} this run, ${agents.Paid.spent():.4f} in the lab ledger; "
          f"{out / 'index.html'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["rehearse", "dry", "paid"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--run", default="")
    a = ap.parse_args()
    if a.mode == "rehearse":
        run(agents.Rehearsal(REHEARSAL), a.run or "rehearsal")
        return 0
    if a.mode == "dry":
        cov = Coverage.load(SCENE)
        print(f"Scene: {cov.heading}; {len(cov.clips)} clips; full render {len(cov.render())} chars")
        for role, model, effort, worst in agents.worst_case_table():
            print(f"  {role:9} {model} {effort}: worst case per call about ${worst:.3f}")
        print(f"Lab cap ${agents.LAB_CAP_USD:.2f}; spent so far ${agents.Paid.spent():.4f}. Expected for the scenario: "
              "about 11 conductor + 11 reply + 4-7 author calls.")
        return 0
    if not a.yes:
        print("A paid run needs --yes (the person's yes first).")
        return 2
    n = len([p for p in agents.RUNS.glob("run*") if p.is_dir()]) + 1
    run(agents.Paid(a.run or f"run{n}"), a.run or f"run{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
