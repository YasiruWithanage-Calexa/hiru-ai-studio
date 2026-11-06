"""Zora's gate (plan/2026-11-06e §4.6 steps 2, 3 and 6): the planner's own mend and checks on the whole plan, by id.

    judge(scene, plan, …)          jonathan_mend then jonathan_check (ADR 0009: reached by id, never imported)
    stable_key(problem, handles)   a problem's key with its shot numbers turned into kernel handles: a problem a turn
                                   did not cause keeps its key when an insert renumbers the shots
    new_problems(before, after)    only what THIS turn introduced counts (repair, don't redo); old ones are left alone
    protect(...)                   a take the person set is kept: when the mend would lengthen it, it is put back and
                                   the overrun is reported with the way out (Hiru: report, never trim, and the person's
                                   value lands)
    overruns(problems)             a line longer than any take, per shot, with the way out: reported, never trimmed

This file and `zora_kernel/step.py` are the only Zora files that name the planner's parts
(`tests/zora/test_removal.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from hiru_ai.core import parts

Row = dict[str, Any]
PLANNER = "jonathan"  # the planner whose stored plan Zora edits, and whose checks are Zora's gate
CHECK, MEND, SEAMS = f"{PLANNER}_check", f"{PLANNER}_mend", f"{PLANNER}_seams"


def _step(ident: str) -> Any:
    return parts.step(ident, "step")


@dataclass
class Judged:
    plan: Row
    mended: list[str] = dc_field(default_factory=list)
    problems: list[Row] = dc_field(default_factory=list)  # {code, sentence, shots, fix, key}
    measures: list[Row] = dc_field(default_factory=list)
    score: tuple[int, int] = (0, 0)  # (faults, craft gaps): lower is better
    malformed: str = ""

    @property
    def faults(self) -> list[Row]:
        return [p for p in self.problems if p.get("fix") != "report"]

    @property
    def gaps(self) -> list[Row]:
        return [m for m in self.measures if m.get("status") == "missed"]


def wire_errors(scene: Row, plan: Row) -> list[str]:
    """The planner's own validation of the plan's shape ([] = it reads)."""
    out = _step(CHECK).run({"scene": scene, "plan": plan})
    return [str(out["malformed"])] if out.get("malformed") else []


def judge(scene: Row, plan: Row, *, removed: list[Row] | None = None, craft: Row | None = None,
          mend: bool = True) -> Judged:
    """Mend (unless `mend=False`), then check and measure. A plan that cannot be read comes back `malformed`."""
    removed = list(removed or [])
    mended: list[str] = []
    if mend:
        out = _step(MEND).run({"scene": scene, "plan": plan, "removed": removed})
        if "malformed" in out:
            return Judged(plan=plan, malformed=str(out["malformed"]), score=(99, 99))
        plan = out["plan"]
        mended = list(out["mended"]) + [p["sentence"] for p in out.get("dropped") or []]
    found = _step(CHECK).run({"scene": scene, "plan": plan, "removed": removed, "craft": craft or {}})
    if found.get("malformed"):
        return Judged(plan=plan, malformed=str(found["malformed"]), score=(99, 99))
    score = found.get("score") or [0, 0]
    return Judged(plan=plan, mended=mended, problems=list(found["problems"]),
                  measures=list(found.get("measures") or []), score=(int(score[0]), int(score[1])))


def stable_key(problem: Row, handles: list[str]) -> str:
    """The problem's key with every part that is one of its shots' numbers replaced by that shot's handle."""
    shots = {int(n) for n in problem.get("shots") or []}
    key = str(problem.get("key") or f"{problem.get('code')}:{problem.get('sentence')}")
    parts_ = [handles[int(p) - 1] if p.isdigit() and int(p) in shots and 1 <= int(p) <= len(handles) else p
              for p in key.split(":")]
    return ":".join(parts_)


def new_problems(before: list[Row], before_handles: list[str], after: list[Row], after_handles: list[str]
                 ) -> list[Row]:
    """The problems in `after` that `before` did not have (by stable key)."""
    old = {stable_key(p, before_handles) for p in before}
    return [p for p in after if stable_key(p, after_handles) not in old]


def protect(plan_before_mend: Row, judged: Judged, pinned_blocks: dict[tuple[int, ...], int]) -> tuple[Row, list[str]]:
    """Put back a take the person set when the mend lengthened it (the shot is found by the blocks it shows). → (the
    plan, the overruns to report)."""
    plan = judged.plan
    notes = []
    for shot in plan["shots"]:
        want = pinned_blocks.get(tuple(shot["blocks"]))
        if want is not None and shot["take_s"] != want:
            notes.append(f"S{shot['n']:02d}: you set a {want} s take; what it shows needs {shot['take_s']} s, so its "
                         f"end would be cut off. The way out: a {shot['take_s']} s take, or split it at a block.")
            shot["take_s"] = want
            shot["use_s"] = min(shot["use_s"], want)
    return plan, notes


def overruns(problems: list[Row]) -> list[str]:
    """A line (or an action) longer than the longest take, reported per shot with the way out. Never trimmed."""
    return [f"{p['sentence']} The way out is the person's: a shorter line in their own words (a card), or keep it and "
            "accept that Veo will not fit it all." for p in problems if p.get("code") == "clock"
            and p.get("fix") == "report"]


def seams(end_state: Row, *, next_plan: Row | None, next_link: str, next_start: Row | None,
          next_number: int) -> list[Row]:
    """The join between this scene's NEW end and the next scene's opening, as the planner judges it ([] = it holds,
    the next scene does not carry on from this one, or it is not planned yet)."""
    if not next_plan or not next_link:
        return []
    out = _step(SEAMS).run({"before": end_state, "link": next_link, "start": next_start, "after": next_plan,
                            "number": next_number})
    return list(out.get("problems") or [])
