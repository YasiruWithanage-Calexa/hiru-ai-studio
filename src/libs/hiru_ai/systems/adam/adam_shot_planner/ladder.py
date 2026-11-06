"""The fixer ladder (plan/2026-11-05 T3): one problem at a time, code first, then a small model, then a bigger one.

    for each problem (adam_problems), cheapest rung first:
        rung 0   code mended what it could before this (`adam_problems` mend, `adam_split`)
        rung 1   `adam_fixer` on the tier fixer.yaml gives this kind of problem as its first
        rung 2   `adam_fixer` on the next tier, told why the first fix was refused
        left     reported, never hidden and never trimmed

After EVERY fix code checks the whole plan again: `adam_fidelity` drops an added moment that invents story, `adam_split`
repairs a crowded card, `check_revision` holds the fixer to its disposition (an `add` that names a face must fill it, a
removal must answer a note), and `adam_score` ranks the plan against the one before. A fix that breaks something, does
not solve the problem, or ranks worse is refused and goes up a rung. A fixer is an editor, not an author: it changes a
card or adds a moment and cannot rewrite the plan, so the one take's whole-scene intent stays.

No loops: at most `rounds` model rungs per problem and one pass over the problems. Pure orchestration over the agent and
the steps by id: no database, no network except the model calls the fixer makes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import AdamPlan, ShotCard
from contracts.adam.problems import Problem
from contracts.adam.screening import Noted, check_revision, drop_moments, remap_sound
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.models import tier_names
from hiru_ai.core.panels import PanelKit

_log = logging.getLogger(__name__)
CONFIG = Path(__file__).with_name("fixer.yaml")
AROUND = 2  # cards on each side of the problem's card that the fixer is shown
MAX_ROUNDS = 3


@dataclass(frozen=True)
class FixerConfig:
    """`fixer.yaml`: which tier each rung of each kind of problem runs on."""

    rounds: int
    tiers: dict[str, str]  # the file's own names -> a tier of core/models.yaml
    kinds: dict[str, tuple[str, ...]]  # kind of problem -> its rungs, cheapest first

    def rungs(self, kind: str) -> list[tuple[str, str]]:
        """-> [(the rung's name in the file, the model tier)] for a kind, at most `rounds` of them. A mechanical problem
        that code could not mend is treated as local: it has a card to look at."""
        names = self.kinds.get(kind) or self.kinds.get("local") or ()
        return [(n, self.tiers[n]) for n in names[: self.rounds]]


def load_config(path: Path | None = None) -> FixerConfig:
    """The ladder's settings, checked: every rung names a tier of this file and every tier is a tier the models know."""
    path = path or CONFIG
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tiers = {str(k): str(v) for k, v in (raw.get("tiers") or {}).items()}
    kinds = {str(k): tuple(str(x) for x in v) for k, v in (raw.get("kinds") or {}).items()}
    rounds = int(raw.get("rounds") or 2)
    known = set(tier_names())
    problems = [f"tier {name!r} is {tier!r}, which models.yaml does not have" for name, tier in tiers.items()
                if tier not in known]
    problems += [f"kind {kind!r} names rung {n!r}, which `tiers` does not have" for kind, names in kinds.items()
                 for n in names if n not in tiers]
    if not 1 <= rounds <= MAX_ROUNDS:
        problems.append(f"rounds is {rounds}; a problem gets 1 to {MAX_ROUNDS} model rungs")
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return FixerConfig(rounds=rounds, tiers=tiers, kinds=kinds)


def in_moment_order(moments: list[Any], cards: list[ShotCard]) -> tuple[list[ShotCard], dict[int, int]]:
    """The cards in the order of the moments they show, numbered again. -> (the cards, current number -> new number).

    A card's place is decided by its moments: the plan's rule is that the cards keep the moments in the order the plan
    gives them. A fixer that adds a moment and inserts its card a card too early or too late made the commonest
    refusal in the first real build (17 of 26), so code puts the card where its moment is. A card holds only moments,
    so nothing is changed, deleted or invented; a card whose own moments are out of order is left for `adam_fidelity`
    to refuse."""
    at = {m.id: i for i, m in enumerate(moments)}
    ordered = sorted(cards, key=lambda c: min((at[m] for m in c.moments if m in at), default=len(at)))
    moved = {c.number: i for i, c in enumerate(ordered, start=1)}
    return [c.model_copy(update={"number": moved[c.number]}) for c in ordered], moved


def _dump(plan: AdamPlan) -> dict[str, Any]:
    return dict(plan.model_dump(mode="json", by_alias=True))


@dataclass
class Outcome:
    """What became of one problem."""

    problem: Problem
    fixed: bool = False
    rung: int = 0  # the model rung that fixed it (1 or 2); 0 = none did
    tier: str = ""
    ops: list[int] = field(default_factory=list)  # the numbers of the operations that answered it, in the whole record
    reason: str = ""  # why it was left, when it was
    tries: list[dict[str, Any]] = field(default_factory=list)  # each rung: the tier, whether it stood, why not

    def row(self) -> dict[str, Any]:
        return {"problem": self.problem.id, "kind": self.problem.kind, "source": self.problem.source,
                "code": self.problem.code, "card": self.problem.card, "cell": self.problem.cell,
                "note_id": self.problem.note_id, "fixed": self.fixed, "rung": self.rung, "tier": self.tier,
                "reason": self.reason, "tries": self.tries}


@dataclass
class Fixed:
    plan: AdamPlan
    outcomes: list[Outcome]
    # every operation that stood, numbered across the whole ladder
    ops: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # added moments a fix wrote that `adam_fidelity` refused
    splits: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(o.fixed for o in self.outcomes)


@dataclass
class _Try:
    ok: bool
    plan: AdamPlan
    ev: dict[str, Any]
    why: list[str] = field(default_factory=list)
    ops: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    splits: list[dict[str, Any]] = field(default_factory=list)


class Ladder:
    def __init__(self, ctx: RunContext, panel: Any, scene: dict[str, Any], *, config: FixerConfig | None = None,
                 events: list[dict[str, Any]] | None = None) -> None:
        self.ctx, self.panel, self.scene = ctx, panel, scene
        self.config = config or load_config()
        self.events = events if events is not None else []
        self.kit = PanelKit(panel.ID, ctx)
        self.judge = parts.module("step", "adam_score", "logic")

    # ── the code's whole opinion of a plan ──────────────────────────────────────────────────────

    def evaluate(self, plan: AdamPlan) -> dict[str, Any]:
        return dict(self.panel.evaluate(self.kit, self.scene, _dump(plan)))

    @staticmethod
    def open_problems(ev: dict[str, Any]) -> list[Problem]:
        """What code still finds wrong in an evaluation (no notes: those are the critic's)."""
        found = parts.step("adam_problems", "step").run({"reports": {k: ev[k] for k in (
            "fit", "coverage", "continuity", "feasibility")}, "notes": [], "limit": 99})
        return [Problem.model_validate(p) for p in found["problems"]]

    # ── what the fixer is shown ─────────────────────────────────────────────────────────────────

    @staticmethod
    def around(plan: AdamPlan, problem: Problem) -> tuple[list[Any], list[ShotCard]]:
        cards = (plan.cards if not problem.card else
                 [c for c in plan.cards if abs(c.number - problem.card) <= AROUND])
        shown = {m for c in cards for m in c.moments}
        return [m for m in plan.moments if m.id in shown], list(cards)

    def noted(self, problem: Problem) -> Noted:
        """The problem as the note `check_revision` holds the fixer to: a face code wants is an `add` that must fill its
        cell; a note keeps its own kind and cell; any other fault is a change."""
        if problem.source == "note":
            kind, cell = problem.note_kind or "change", problem.cell
        elif problem.code.startswith("hole:"):
            kind, cell = "add", problem.cell
        else:
            kind, cell = "change", ""
        return Noted(id=problem.id, lens=problem.source, severity="high", kind=kind, card=problem.card, cell=cell,
                     note=problem.text)

    # ── one fix, checked ────────────────────────────────────────────────────────────────────────

    def attempt(self, current: AdamPlan, before: dict[str, Any], problem: Problem, tier: str, earlier: str) -> _Try:
        moments, cards = self.around(current, problem)
        report = parts.step("adam_notes", "step").run({k: before[k] for k in (
            "fidelity", "fit", "continuity", "feasibility", "coverage", "score")})["text"]
        answer = agents.build("adam_fixer").run({
            "scene": self.scene, "concept": current.treatment.concept, "problem": problem.model_dump(),
            "moments": [m.model_dump(mode="json", by_alias=True) for m in moments],
            "cards": [c.model_dump(mode="json", by_alias=True) for c in cards], "report": report,
            "earlier": earlier}, self.ctx, tier=tier)
        # One problem, one disposition: it answers by the problem's id whatever the model called it.
        answer = answer.model_copy(update={"dispositions": [d.model_copy(update={"note_id": problem.id})
                                                            for d in answer.dispositions[:1]]})
        revised = answer.apply(current.moments, current.cards)
        new_moments, new_cards, numbers = revised.moments, revised.cards, dict(revised.renumbered)
        fidelity = parts.step("adam_fidelity", "step").run({
            "scene": self.scene, "moments": [m.model_dump(mode="json") for m in new_moments]})
        dropped = list(fidelity["dropped"])
        if dropped:
            new_moments, new_cards, again = drop_moments(new_moments, new_cards, set(dropped))
            numbers = {old: again[new] for old, new in numbers.items() if new in again}
        new_cards, placed = in_moment_order(new_moments, new_cards)
        numbers = {old: placed[new] for old, new in numbers.items() if new in placed}
        mended = parts.step("adam_split", "step").run({
            "scene": self.scene, "moments": [m.model_dump(mode="json", by_alias=True) for m in new_moments],
            "cards": [c.model_dump(mode="json", by_alias=True) for c in new_cards],
            "treatment": _dump(current)["treatment"]})
        if mended["changed"]:
            new_cards = [ShotCard.model_validate(c) for c in mended["cards"]]
            numbers = {old: mended["renumbered"][new] for old, new in numbers.items() if new in mended["renumbered"]}
        sound = remap_sound(current.sound_map, numbers, {m.id for m in new_moments})
        plan = current.model_copy(update={"moments": new_moments, "cards": new_cards, "sound_map": sound})
        after = self.evaluate(plan)

        why = list(revised.skipped)
        note = self.noted(problem)
        why += check_revision(
            [note], answer, revised, filled={c["id"] for c in after["coverage"]["cells"] if c["ok"]},
            known={c["id"] for c in [*before["coverage"]["cells"], *after["coverage"]["cells"]]},
            first_kinds={m.kind for m in current.moments if m.tier != "script"},
            now_kinds={m.kind for m in new_moments if m.tier != "script"})
        declined = next((d.declined.strip() for d in answer.dispositions if d.declined.strip()), "")
        if declined:
            why.append(f"the fixer declined: {declined}")
        if problem.source == "code" and revised.removals:
            why.append("a fix for a fault code found never removes a moment")
        if after["fidelity"]["counts"]["breaks"] > before["fidelity"]["counts"]["breaks"]:
            why.append("it breaks the script: " + "; ".join(
                f"{b['where']}: {b['reason']}" for b in after["fidelity"]["breaks"][:2]))
        if problem.source == "code" and not declined and not why:
            still = sum(p.code == problem.code for p in self.open_problems(after))
            was = sum(p.code == problem.code for p in self.open_problems(before))
            if still >= was:
                why.append(f"it does not solve the problem: code still finds {problem.code}")
        if not why:
            lost = self.judge.lost_cells([before["score"], after["score"]])
            if self.judge.rank(after["score"], lost[1]) > self.judge.rank(before["score"], lost[0]):
                why.append("the plan scores worse after it: " + "; ".join(
                    str(r) for r in (after["score"].get("loss_reasons") or [])[:2] or ["it loses a required face "
                                                                                       "or adds an overrun"]))
        return _Try(ok=not why, plan=plan, ev=after, why=why, ops=_ops(answer, revised), skipped=revised.skipped,
                    dropped=dropped, splits=list(mended["splits"]))

    # ── the ladder ──────────────────────────────────────────────────────────────────────────────

    def run(self, plan: AdamPlan, problems: list[Problem]) -> Fixed:
        current, ev = plan, self.evaluate(plan)
        done = Fixed(plan=plan, outcomes=[])
        for problem in problems:
            outcome = Outcome(problem=problem)
            earlier = ""
            for rung, (name, tier) in enumerate(self.config.rungs(problem.kind), start=1):
                try:
                    tried = self.attempt(current, ev, problem, tier, earlier)
                except Exception as exc:  # a fixer that cannot answer is a rung that failed, not a scene that did
                    _log.warning("adam_fixer failed on %s (%s)", problem.id, tier, exc_info=True)
                    outcome.tries.append({"rung": rung, "name": name, "tier": tier, "stood": False,
                                          "why": [f"the fixer could not answer ({type(exc).__name__})"]})
                    earlier = "the smaller model could not answer; do the whole fix."
                    continue
                outcome.tries.append({"rung": rung, "name": name, "tier": tier, "stood": tried.ok, "why": tried.why})
                self.events.append({"stage": "fix", "kind": "fixed" if tried.ok else "refused", "problem": problem.id,
                                    "problem_kind": problem.kind, "text": problem.text, "rung": rung, "tier": tier,
                                    "why": tried.why})
                if tried.ok:
                    offset = len(done.ops)
                    numbered = [{**o, "n": offset + o["n"], "note_id": problem.note_id or problem.id}
                                for o in tried.ops]
                    done.ops += numbered
                    done.skipped += tried.skipped
                    done.dropped += tried.dropped
                    done.splits += tried.splits
                    outcome.fixed, outcome.rung, outcome.tier = True, rung, tier
                    outcome.ops = [o["n"] for o in numbered if o["applied"]]
                    current, ev = tried.plan, tried.ev
                    break
                earlier = "; ".join(tried.why)
            if not outcome.fixed:
                outcome.reason = outcome.tries[-1]["why"][0] if outcome.tries and outcome.tries[-1]["why"] \
                    else "no model rung is set for this kind of problem"
                self.events.append({"stage": "fix", "kind": "reported", "problem": problem.id,
                                    "problem_kind": problem.kind, "text": problem.text, "reason": outcome.reason})
            done.outcomes.append(outcome)
        done.plan = current
        return done


def _ops(answer: Any, revised: Any) -> list[dict[str, Any]]:
    """The fixer's operations as a record: what each did, to what, and whether it applied (numbered from 1 here)."""
    rows = []
    for n, op in enumerate(answer.operations, start=1):
        target = op.id if op.op == "remove_moment" else (op.moment.id if op.op == "add_moment" and op.moment
                                                         else op.number)
        rows.append({"n": n, "op": op.op, "why": op.why, "target": target, "applied": bool(revised.applied[n - 1])})
    return rows
