"""One Zora turn in the lab (plan/2026-11-06e §3, Phase 3), on the product's own code: the kernel, the dependency graph,
the board, the planner's gate, the delivery check and the ledger (`hiru_ai.steps.zora.*`). Only the model calls are the
lab's, passed in as `call(role, system, user, schema) -> dict`, so the same pipeline runs on recorded answers (free)
and on real ones (paid, `run.py`).

    arm A   ONE author call for all of the turn's tasks (this plan's design)
    arm B   Nova's seats: the four crafts of today's `director_board` (cinematography, timing, sound, continuity) as
            separate calls on one snapshot, each owning its effects; their ops applied in a fixed order

Both arms get the same input (the case's recorded conductor answer), so the end plans differ only by the author side.
`score(case, outcome)` checks what code can check; reply-side expectations are not measured here.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from contracts.zora import effects as E
from contracts.zora import ops as O
from contracts.zora.doc import ZoraDoc
from contracts.zora.render import addressable
from contracts.zora.tasks import Task, merge_tasks
from hiru_ai.steps.zora.zora_board import gate
from hiru_ai.steps.zora.zora_board.logic import settle
from hiru_ai.steps.zora.zora_deliver.logic import report, retask, undelivered
from hiru_ai.steps.zora.zora_deps.logic import plan_tasks, recut_guard
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from hiru_ai.steps.zora.zora_kernel.step import planner_validation
from hiru_ai.steps.zora.zora_ledger.logic import build, change_lines
from contracts.zora import wire as schema

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[1]
PRIMER = ROOT / "src" / "libs" / "hiru_ai" / "agents" / "jonathan" / "jonathan_author" / "prompts" / "system.md"
Call = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]
Row = dict[str, Any]
MAX_REPAIRS = 1  # the lab's: the product allows 2 (plan §4.6); one is enough to see whether repair helps
SEATS: dict[str, tuple[str, ...]] = {
    "cinematography": ("shot.size", "shot.angle", "shot.lens", "shot.link", "shot.why", "shot.ir.cinematography",
                       "shot.ir.first_frame", "shot.ir.beats", "treatment.approach", "treatment.key_image",
                       "treatment.logline"),
    "continuity": ("staging.marks", "staging.zones", "shot.ir.subjects", "shot.ir.setting", "shot.ir.lighting",
                   "treatment.colour", "treatment.geography", "shot.over"),
    "sound": ("shot.sound.ambience", "shot.sound.effects", "shot.sound.music", "shot.sound.silence", "shot.ir.audio"),
    "timing": ("shot.take_s", "shot.use_s", "shot.order", "shot.added", "sequence.bounds", "sequence.title",
               "sequence.purpose", "treatment.arc"),
}


def fixture(scene: str) -> ZoraDoc:
    raw = json.loads((ROOT / "tests" / "eval" / "zora" / "fixtures" / f"{scene}.json").read_text(encoding="utf-8"))
    return ZoraDoc(plan=raw["plan"], scene=raw["scene"])


def conductor_system() -> str:
    return (LAB / "prompts" / "conductor.md").read_text(encoding="utf-8")


def author_system(seat: str = "") -> str:
    text = PRIMER.read_text(encoding="utf-8") + (LAB / "prompts" / "author.md").read_text(encoding="utf-8")
    if seat:
        mine = ", ".join(SEATS[seat])
        text += (f"\n\nYOU ARE THE TEAM'S {seat.upper()} SEAT. You own and may write only: {mine}. Other seats own the "
                 "rest and answer at the same time; leave their parts to them.")
    return text


def conductor_message(doc: ZoraDoc, message: str, transcript: list[str]) -> str:
    talk = "\n".join(transcript[-4:]) or "(no earlier messages)"
    return f"CONVERSATION (recent):\n{talk}\n\n{addressable(doc)}\n\nLATEST MESSAGE FROM THE DIRECTOR:\n{message}"


def _numbers(k: ZoraKernel, handles: tuple[str, ...]) -> list[int]:
    return sorted(n for h in handles if (n := k.number_of(h)) is not None)


def author_message(k: ZoraKernel, tasks: list[Task], done: list[str], transcript: list[str], *, variants: int = 0,
                   faults: list[str] | None = None) -> str:
    whole = any(not t.scope for t in tasks)
    only = None if whole else {n for t in tasks for n in _numbers(k, t.scope)}
    lines = ["CONVERSATION (recent):\n" + ("\n".join(transcript[-4:]) or "(none)"), "", addressable(k.doc(), only), ""]
    lines.append("ALREADY DONE THIS TURN:\n" + ("\n".join(f"- {d}" for d in done) or "- nothing yet"))
    lines.append("\nTASKS THIS TURN:")
    for i, t in enumerate(tasks, start=1):
        where = "any shot" if not t.scope else ", ".join(O.code(n) for n in _numbers(k, t.scope))
        lines.append(f"{i}. {t.instruction or t.reason}\n   YOU MAY WRITE ONLY: "
                     + ", ".join(t.allowed) + f"\n   ON: {where}\n   MUST CHANGE: " + ", ".join(t.writes))
    if variants:
        lines.append(f"\nGive {variants} VARIANTS (each a label and its own operations); leave `ops` empty.")
    if faults:
        lines.append("\nAFTER YOUR EDIT THE PLANNER'S CHECKS FOUND (fix exactly these; change nothing else):\n"
                     + "\n".join(f"- {f}" for f in faults))
    return "\n".join(lines)


@dataclass
class Outcome:
    case: str
    arm: str
    lane: str
    calls: dict[str, int] = field(default_factory=dict)
    before: Row = field(default_factory=dict)  # with handles
    after: Row = field(default_factory=dict)  # with handles, before the mend
    end_plan: Row = field(default_factory=dict)  # the plan as the gate leaves it (mended)
    changes: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    undelivered: list[str] = field(default_factory=list)
    new_faults: list[Row] = field(default_factory=list)
    offer: str = ""
    proposals: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def data(self) -> Row:
        return {k: v for k, v in self.__dict__.items() if k not in ("before", "after")}


def _ops(answer: Row) -> list[Row]:
    return [schema.to_op(o) for o in answer.get("ops") or [] if isinstance(o, dict)]


def _faults(problems: list[Row]) -> list[Row]:
    return [p for p in problems if p.get("fix") != "report"]


def run_turn(case: Row, call: Call, *, arm: str = "A", transcript: list[str] | None = None) -> Outcome:
    """The case's (last) message through the turn, with its recorded conductor answer."""
    turns = case.get("turns") or [{"person": case["message"], "conduct": case["conduct"]}]
    conduct = turns[-1]["conduct"]
    doc = fixture(case["scene"])
    k = ZoraKernel(doc, validate=planner_validation(doc.scene))
    out = Outcome(case=case["id"], arm=arm, lane=conduct["lane"])
    base = gate.judge(doc.scene, k.export(), mend=False)
    base_handles = k.handles()
    out.before = k.export(handles=True)
    r0 = k.apply(conduct["ops"], by="conductor")
    out.refused += [f"{x['reason']}" for x in r0.rejected]
    stale = plan_tasks(k, r0.changes)
    handles = k.handles()
    asked = [Task(tuple(E.normalize_effect(e) for e in t["writes"] if E.normalize_effect(e)),
                  tuple(handles[n - 1] for n in t["scope"] if 1 <= n <= len(handles)),
                  instruction=t["instruction"], may=tuple(t.get("may") or ()), origin="conductor", user_asked=True)
             for t in conduct["tasks"]]
    tasks = merge_tasks([*asked, *stale.tasks])
    out.offer = recut_guard(conduct["lane"], "", len(doc.shots), stale)
    if out.offer:
        k.undo(r0)
        out.after = out.end_plan = k.export(handles=True)
        return out
    done = [f"{line.where}: {line.text}" for line in change_lines(out.before, k.export(handles=True))]
    talk = list(transcript or [])
    if tasks and conduct["lane"] not in ("chat", "clarify", "cannot", "translate"):
        variants = int(conduct.get("variants") or 0) if conduct["lane"] == "options" else 0
        before_author = k.export()
        answers = _author(call, arm, k, tasks, done, talk, variants, out)
        if variants:
            for v in (answers[0].get("variants") or [])[:variants]:
                trial = ZoraKernel(k.doc(), validate=k.validate)
                kept = settle([schema.to_op(o) for o in v.get("ops") or []], tasks, before_author, handles=k.handles(),
                              locked=k.locked)
                res = trial.apply(kept.kept, by="author")
                judged = gate.judge(doc.scene, trial.export())
                new = gate.new_problems(base.problems, base_handles, judged.problems, trial.handles())
                if res.applied and not _faults(new):
                    out.proposals.append({"label": v.get("label", ""), "ops": res.applied})
        else:
            _apply_answers(k, answers, tasks, before_author, out)
            # deliver: what was declared and did not change gets ONE more task
            missing = undelivered(tasks, out.before, k.export(handles=True))
            again = retask(missing, tasks, locked=k.locked, handles=k.handles())
            if again:
                done = [f"{x.where}: {x.text}" for x in change_lines(out.before, k.export(handles=True))]
                before_retask = k.export()
                _apply_answers(k, _author(call, arm, k, again, done, talk, 0, out), again, before_retask, out)
    out.after = k.export(handles=True)
    judged = gate.judge(doc.scene, k.export())
    new = _faults(gate.new_problems(base.problems, base_handles, judged.problems, k.handles()))
    for _ in range(MAX_REPAIRS if new and conduct["lane"] not in ("options",) else 0):
        before_repair = k.export()
        fix = Task(tuple(dict.fromkeys(e for t in tasks for e in t.allowed)), (), instruction="repair",
                   origin="repair")
        answers = _author(call, arm, k, [fix], [], talk, 0, out, faults=[p["sentence"] for p in new])
        snap = k._snapshot()
        _apply_answers(k, answers, [fix], before_repair, out, by="repair")
        again = gate.judge(doc.scene, k.export())
        worse = _faults(gate.new_problems(base.problems, base_handles, again.problems, k.handles()))
        if len(worse) < len(new):
            judged, new, out.after = again, worse, k.export(handles=True)
        else:
            k._restore(snap)
            out.log.append("repair pass not better: dropped")
    out.end_plan = judged.plan
    out.new_faults = new
    out.changes = [f"{x.where}: {x.text}" for x in change_lines(out.before, out.after)]
    out.undelivered = report(undelivered(tasks, out.before, out.after), tasks, locked=k.locked, handles=k.handles())
    return out


def _author(call: Call, arm: str, k: ZoraKernel, tasks: list[Task], done: list[str], talk: list[str], variants: int,
            out: Outcome, *, faults: list[str] | None = None) -> list[Row]:
    if arm == "A":
        out.calls["author"] = out.calls.get("author", 0) + 1
        user = author_message(k, tasks, done, talk, variants=variants, faults=faults)
        return [call("author", author_system(), user, schema.author_schema())]
    answers = []
    for seat, owned in SEATS.items():
        mine = [Task(tuple(e for e in t.writes if e in owned), t.scope, instruction=t.instruction,
                     may=tuple(e for e in t.may if e in owned), origin=t.origin) for t in tasks]
        mine = [t for t in mine if t.allowed]
        if not mine:
            continue
        out.calls[seat] = out.calls.get(seat, 0) + 1
        user = author_message(k, mine, done, talk, variants=variants, faults=faults)
        answers.append({**call(f"seat:{seat}", author_system(seat), user, schema.author_schema()), "_seat": seat})
    return answers


def _apply_answers(k: ZoraKernel, answers: list[Row], tasks: list[Task], plan: Row, out: Outcome,
                   by: str = "author") -> None:
    order = list(SEATS)  # arm B: structural seats (timing) last, so the others' numbers still hold
    for answer in sorted(answers, key=lambda a: order.index(a["_seat"]) if a.get("_seat") in order else -1):
        seat = f"the {answer['_seat']} seat" if answer.get("_seat") else "the director"
        kept = settle(_ops(answer), tasks, plan, handles=k.handles(), locked=k.locked, seat=seat)
        out.refused += kept.refused
        res = k.apply(kept.kept, by=by)
        out.refused += [f"{seat}'s {x['op'].get('op') if isinstance(x['op'], dict) else x['op']}: {x['reason']}"
                        for x in res.rejected]
        if answer.get("notes"):
            out.notes.append(str(answer["notes"]))


# ── scoring ─────────────────────────────────────────────────────────────────────────────────────────


def score(case: Row, out: Outcome) -> dict[str, bool | None]:
    """Each expectation code can check: True / False, or None when the lab does not measure it."""
    exp = case["expect"]
    doc = fixture(case["scene"])
    after = out.end_plan or out.after
    got: dict[str, bool | None] = {"lane": out.lane == exp["lane"], "no_offer": not out.offer}
    if exp.get("effects_delivered"):
        changed = E.changed_effects(out.before, out.after)
        got["effects_delivered"] = set(exp["effects_delivered"]) <= changed
    if exp.get("planner_problems_not_worse"):
        got["planner_problems_not_worse"] = not out.new_faults
    if exp.get("lines_verbatim"):
        got["lines_verbatim"] = all(s.get("lines") == [f"L{b}" for b in sorted(s.get("blocks") or [])
                                                       if f"L{b}" in doc.lines] for s in after.get("shots") or [])
    if "use_total_at_most" in exp:
        got["use_total"] = sum(int(s["use_s"]) for s in after.get("shots") or []) <= int(exp["use_total_at_most"])
    if "proposals" in exp:
        got["proposals"] = len(out.proposals) == int(exp["proposals"])
    if exp.get("plan_unchanged"):
        got["plan_unchanged"] = not out.changes
    for key in ("claims_match_state", "no_unbacked_promise", "staged", "end_state"):
        if key in exp:
            got[key] = None  # the reply and the translator are not in this lab
    return got


def passed(checks: dict[str, bool | None]) -> bool:
    return all(v is not False for v in checks.values())


def ledger_of(out: Outcome) -> Row:
    led = build(out.before, out.after, refused=out.refused, undelivered=out.undelivered, attempted=True,
                problems=[p["sentence"] for p in out.new_faults], offer=out.offer)
    return {"ops": led.event(), "gate": led.gate()}
