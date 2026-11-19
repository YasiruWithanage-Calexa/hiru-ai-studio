"""Action-budget lab (2026-11-18), step 3: does Raphael keep the budget when it is told AND checked?

    python lab/action_budget/replan.py dry                 free: the budget check on the SAVED e2e plans: the faults
                                                           Raphael would get back
    python lab/action_budget/replan.py budget --yes        paid: Raphael re-plans the scenes with the lab rule H-91 and
                                                           the blocking check (cap per scene below)

Scenes (Api Denna v2, saved breakdown memory and packets of lab/llm_reader/runs/e2e):
- E01-S02 "Anudi arrives": the car stops, she gets out, the umbrella opens in the rain (the shot-02 problem);
- E01-S01 Kasun's tea stall: lift the flask, pour, set it down, take the cup in one clip.

What the arm changes, in THIS PROCESS ONLY (nothing in src/, nothing in the database):
- RULE   `h91_action_budget.md` is added as a house rule on Raphael's `coverage` topic;
- CHECK  `contracts.raphael.checks.check_stage1` / `check_stage2` gain the budget (count.py's counter) as a BLOCKING
         fault, so every `put_clips` report shows it and `finish` is refused until Raphael splits the clip.

Output: runs/replan/<scene>/ (12_raphael/<scene>.json, plan.txt, prompts_fixed.md, checks_fixed.md, spend.txt) and
runs/replan/compare.md (before/after: clips, hard actions, over budget).
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "lab" / "coverage"), str(ROOT / "src" / "libs"), str(ROOT / "src"),
                str(ROOT / "lab")]

import count  # noqa: E402  (lab/action_budget/count.py)

SCENES = ["E01-S02", "E01-S01"]
E2E = ROOT / "lab" / "llm_reader" / "runs" / "e2e" / "12_raphael"
RULE_FILE = HERE / "h91_action_budget.md"
SCENE_CAP_USD = 0.40
HARD_MAX, ALL_MAX = 1, 3
OUT = HERE / "runs" / "replan"


# ── the check ──────────────────────────────────────────────────────────────────────────────────────────────────────


def clip_row(clip: Any) -> dict[str, Any]:
    ir = clip.ir if isinstance(clip.ir, dict) else (clip.ir or {})
    beats = [b for b in ir.get("beats") or [] if isinstance(b, dict)]
    return {"source": "lab", "beats": [{"action": str(b.get("action") or "")} for b in beats]}


def advice(m: dict[str, Any]) -> str:
    hard = [w for k, _, w in m["acts"] if k == "hard"]
    parts = []
    if m["hard"] > HARD_MAX:
        parts.append(f"{m['hard']} hard actions ({'; '.join(hard)}): give each its own clip, and open the next clip on "
                     "the result (the door already open, the thing already in the hand)")
    if m["hard"] and m["travel"]:
        parts.append(f"a hard action ({hard[0]}) while a person travels ({m['travel'][0]}): make the hard action its "
                     "own clip (an insert or a still person) and the walk another clip that opens after it")
    if m["total"] > ALL_MAX:
        parts.append(f"{m['total']} actions ({'; '.join(w for _, _, w in m['acts'])}): at most {ALL_MAX} in a clip")
    return "; ".join(parts)


_DOOR = r"(?:car |rear |front |passenger |curbside |curb-side |kerb-side |side )*(?:door|gate|boot)"
OPENED = re.compile(rf"\b(?:already[- ]open|open|opened|ajar)\s+(?:\w+\s+){{0,2}}{_DOOR}\b|\b{_DOOR}\b[^.;]{{0,30}}?\b(?:opens|swings open|stays open|is open|open)\b"
                    rf"|\b(?:opens|pushes|pulls|swings)\s+(?:the\s+)?(?:\w+\s+){{0,2}}{_DOOR}\s*(?:open|outward)?")
CLOSED = re.compile(rf"\b(?:closes|shuts|slams)\s+(?:the\s+|it\b)(?:\w+\s+){{0,2}}(?:{_DOOR})?|\b(?:pushes|presses|pulls|swings)\s+(?:the\s+)?(?:\w+\s+){{0,2}}(?:{_DOOR}|it)\s+(?:shut|closed)\b"
                    rf"|\b{_DOOR}\b[^.;]{{0,30}}?\b(?:closes|shuts|is closed|closed|shut)\b")


def _clip_words(clip: Any) -> str:
    ir = clip.ir if isinstance(clip.ir, dict) else (clip.ir or {})
    beats = " ".join(str(b.get("action") or "") for b in ir.get("beats") or [] if isinstance(b, dict))
    return f"{getattr(clip, 'summary', '') or ''} {beats}".lower()


def door_faults(work: Any) -> list[Any]:
    """Nothing half done (H-91): a door opened, or already open, in some clip and closed in none."""
    from contracts.raphael import checks

    opened = [c for c in work.clips if OPENED.search(_clip_words(c))]
    if not opened or any(CLOSED.search(_clip_words(c)) for c in work.clips):
        return []
    c = opened[0]
    return [checks._fault("action_budget", f"{c.slate or c.id} opens a door (or has it already open) and no clip "
                          "closes it: a person never walks away from an open car door. Add a clip, the person standing "
                          "still, that closes it (H-91), before the walk away.", [c.id], key=f"door_open:{c.id}")]


TURNED_AWAY = re.compile(r"\b(?:facing|faces|turned|turns)\s+(?:away|into the (?:vehicle|car|room|bay|stall|wall)"
                         r"|toward the (?:vehicle|wall|interior))\b|\b(?:back|backs) to (?:the )?(?:camera|lens)\b"
                         r"|\bwith (?:his|her|their) back (?:to|toward)\b|\b(?:initially|still) facing into\b")


def speaker_faults(work: Any) -> list[Any]:
    """A clip with a spoken line that OPENS with the speaker turned away (H-91): the first frame has no face."""
    from contracts.raphael import checks

    out = []
    for clip in work.clips:
        if not (getattr(clip, "speaks", False) or getattr(clip, "lines", None)):
            continue
        ir = clip.ir if isinstance(clip.ir, dict) else (clip.ir or {})
        beats = [b for b in ir.get("beats") or [] if isinstance(b, dict)]
        opening = " ".join([str(beats[0].get("action") or "") if beats else "",
                            *[str(s.get("position") or "") for s in ir.get("subjects") or [] if isinstance(s, dict)],
                            *[str(x) for x in ((ir.get("first_frame") or {}).get("subjects") or [])]]).lower()
        m = TURNED_AWAY.search(opening)
        if m:
            out.append(checks._fault("action_budget", f"{clip.slate or clip.id} carries a spoken line but opens with "
                                     f"the speaker '{m.group(0)}': the first frame has no face. Open the clip with the "
                                     "speaker already turned to the camera's side; put the turn in the clip before "
                                     "(H-91).", [clip.id], key=f"speaker_hidden:{clip.id}"))
    return out


def budget_faults(work: Any) -> list[Any]:
    from contracts.raphael import checks

    out = [*door_faults(work), *speaker_faults(work)]
    for clip in work.clips:
        m = count.measure(clip_row(clip))
        why = count.reasons(m, HARD_MAX, ALL_MAX)
        if why:
            name = clip.slate or clip.id
            out.append(checks._fault("action_budget", f"{name} is over the action budget (house rule H-91): "
                                     f"{advice(m)}.", [clip.id], key=f"action_budget:{clip.id}"))
    return out


def install() -> None:
    """The rule and the blocking check, in this process only."""
    from contracts.raphael import checks

    from hiru_ai.core import house_rules

    deployed = house_rules.load()
    extra = house_rules.parse(RULE_FILE)
    house_rules.rules = lambda: tuple(sorted((*deployed, extra), key=lambda r: r.id))
    assert any(r.id == extra.id for r in house_rules.select(["coverage"]))
    one, two = checks.check_stage1, checks.check_stage2
    checks.check_stage1 = lambda brief, work, *a, **k: [*one(brief, work, *a, **k), *budget_faults(work)]
    checks.check_stage2 = lambda brief, work, *a, **k: [*two(brief, work, *a, **k), *budget_faults(work)]


# ── arms ───────────────────────────────────────────────────────────────────────────────────────────────────────────


class _Work:
    def __init__(self, clips: list[Any]) -> None:
        self.clips = clips


def _saved_clips(path: Path) -> list[Any]:
    from types import SimpleNamespace

    result = json.loads(path.read_text(encoding="utf-8")).get("result") or {}
    return [SimpleNamespace(ir=c.get("ir") or {}, slate=c.get("slate"), id=c.get("id"), summary=c.get("summary", ""),
                            speaks=bool(c.get("speaks")), lines=c.get("lines") or [])
            for c in result.get("clips") or []]


def stats(clips: list[Any]) -> dict[str, int]:
    ms = [count.measure(clip_row(c)) for c in clips]
    return {"clips": len(ms), "hard": sum(m["hard"] for m in ms),
            "over": sum(bool(count.reasons(m, HARD_MAX, ALL_MAX)) for m in ms)}


def dry(source: Path | None = None) -> None:
    for sid in SCENES:
        path = (source / sid / "12_raphael" / f"{sid}.json") if source else (E2E / f"{sid}.json")
        if not path.exists():
            continue
        clips = _saved_clips(path)
        faults = budget_faults(_Work(clips))
        print(f"\n## {sid} (saved plan): {stats(clips)}")
        for f in faults:
            print(f"- {f.line()}")


def budget() -> None:
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    from cinematic.run import load_env

    from hiru_ai.core.settings import get_settings

    load_env()
    os.environ["RAPHAEL_SCENE_CAP_USD"] = str(SCENE_CAP_USD)
    get_settings.cache_clear()
    install()

    import run as lab  # lab/coverage/run.py: the world, shot rows and prompts as the product writes them
    from two_memories.live import raphael_one

    rows = ["| scene | plan | clips | hard actions | over budget | status | cost |", "|---|---|---|---|---|---|---|"]
    for sid in SCENES:
        lab.SID = sid
        w = lab.world()
        out = OUT / sid
        (out / "12_raphael").mkdir(parents=True, exist_ok=True)
        s = raphael_one(out, sid, w["packet"], int(sid[-2:]))
        (out / "spend.txt").write_text(f"{s['status']}, {s['calls']} calls, {s['seconds']} s, ${s['dollars']:.4f}\n",
                                       encoding="utf-8")
        before = stats(_saved_clips(E2E / f"{sid}.json"))
        rows.append(f"| {sid} | saved (no budget) | {before['clips']} | {before['hard']} | {before['over']} | - | - |")
        r = json.loads((out / "12_raphael" / f"{sid}.json").read_text(encoding="utf-8"))
        if r.get("result"):
            after = stats(_saved_clips(out / "12_raphael" / f"{sid}.json"))
            rows.append(f"| {sid} | budget | {after['clips']} | {after['hard']} | {after['over']} | {s['status']} | "
                        f"${s['dollars']:.4f} |")
            lab.write_reports(out, w, r["result"], {"with the fixes": True}, r["ids"], s["status"])
        else:
            rows.append(f"| {sid} | budget | - | - | - | {s['status']} | ${s['dollars']:.4f} |")
    (OUT / "compare.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("arm", choices=["dry", "budget"])
    ap.add_argument("--yes", action="store_true", help="the person said yes to the paid arm")
    ap.add_argument("--scenes", nargs="*", default=SCENES)
    ap.add_argument("--out", default="replan", help="runs/<out>/ (dry: the run to check instead of the saved plans)")
    ap.add_argument("--saved", action="store_true", help="dry: check the e2e saved plans")
    a = ap.parse_args()
    global OUT
    SCENES[:] = a.scenes
    OUT = HERE / "runs" / a.out
    if a.arm == "budget" and not a.yes:
        raise SystemExit(f"paid: Raphael re-plans {len(SCENES)} scenes (cap ${SCENE_CAP_USD} each). Add --yes after "
                         "the person's yes.")
    dry(None if a.saved else OUT) if a.arm == "dry" else budget()


if __name__ == "__main__":
    main()
