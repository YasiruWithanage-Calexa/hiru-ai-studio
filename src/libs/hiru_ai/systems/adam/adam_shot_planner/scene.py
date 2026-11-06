"""One scene through Shot Planner Adam (plan/2026-11-04b §4, §5.5).

    analyse   adam_dramaturg                       what the scene is about
    conceive  adam_director ×3 → adam_distinct     three treatments that differ; a person's stance, or the quick score
    imagine   adam_moment_writer → adam_fidelity   the moments; a script fault is sent back ONCE with its reasons,
                                                    an added moment that invents story is dropped
    stage     adam_blocker
    design    adam_shot_designer → fidelity, fit, continuity, feasibility   sent back ONCE on a fault or an overrun
              adam_sound_designer
    screen    adam_screening                       four critics, one revision; the craft score in code keeps the better
    write     (the caller) adam_write

A scene that cannot be planned raises `Failed` with a reason a person can read; nothing is half-written, and the classic
planner is the way out (plan §5.5: Adam has no rules fallback worth having). Overruns are REPORTED, never trimmed; a
crowded card is first repaired by `adam_split` (plan/2026-11-04c F4), so a plan enters screening with no overrun that
code could mend.

Nothing is lost without a record (plan/2026-11-04c F1): every moment the writer made ends as kept, dropped by fidelity,
removed by a person or removed by a revision for a note, and `adam_ledger` fails the scene when one is in no bucket.
`report.history` keeps the first plan, the cards sent back, the critics' notes, what the revision did and why, and which
version was kept, so a person can see what screening changed.

Plan/2026-11-05 adds the same scene in ONE take (`Planner.plan_take`, `ADAM_MODE=take`): `adam_take` writes the
analysis, the chosen treatment, the moments, the staging and the cards in one call, the sound designer writes the
sound, code checks everything, one critic reads it in four lenses, and the fixer ladder (`ladder.py`) fixes what is
left one problem at a time, a small model first and a bigger one only when code refuses the small model's fix. The
staged `plan` stays beside it.

Pure orchestration over the agents and steps by id: no database here. The caller (graph.py) reads the rows and
writes them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from contracts import sceneplan
from contracts.adam.plan import (
    AdamPlan,
    Block,
    Moment,
    Place,
    SceneAnalysis,
    SceneScript,
    ShotCard,
    SoundMap,
    Staging,
    Treatment,
    norm,
)
from contracts.adam.problems import Problem
from contracts.adam.screening import drop_moments, remap_sound
from contracts.adam.stored import Removed, StoredPlan
from contracts.adam.wire import STANCES
from contracts.shotplan import LEAD_IN_S, LINE_GAP_S, TAIL_S
from contracts.timing import WORDS_PER_SECOND, speech_seconds, words_in
from contracts.veo import VEO_DURATIONS
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.panels import PanelKit
from hiru_ai.systems.adam.adam_shot_planner.ladder import Fixed, Ladder

_log = logging.getLogger(__name__)
Row = dict[str, Any]
NO_MODEL = "Shot Planner Adam needs the AI model, which is not available. Use the classic planner for this scene."
TAKE_BACKOFF_S = 2.0  # the wait before the one retry of a take that could not be made (plan/2026-11-05 R3)
MODES = ("staged", "take")


class Failed(Exception):
    """The scene could not be planned; the message says why, in words a person reads."""


@dataclass
class Unchanged:
    """A scene whose input is the one its stored plan was made from: it is kept as it is (plan/2026-11-05 L5)."""

    stored: StoredPlan


@dataclass
class Planned:
    stored: StoredPlan
    fit: dict[str, Any]
    notes: list[str] = field(default_factory=list)  # what the critics said, for the fit report
    log: list[str] = field(default_factory=list)


# ── the scene, as Adam is given it ───────────────────────────────────────────────────────────────


def script_of(scene: Row, lines: list[Row], *, cast: list[str], place: str, objects: list[str]
              ) -> tuple[SceneScript, dict[str, str]]:
    """The scene's blocks as `SceneScript`, and the map from the short line id an agent sees (L<block>) to the
    dialogue line's real id. A block's index is its position among the blocks that have a line to bind, as in
    `sceneplan.items_for`."""
    items = sceneplan.items_for(scene.get("script") or [], lines)
    line_ids: dict[str, str] = {}
    blocks = []
    for item in items:
        short = None
        if item.is_line:
            short = f"L{item.index}"  # the line at block 4 is L4: the id says where the line is
            line_ids[short] = str(item.line_id)
        blocks.append(Block(index=item.index, kind=item.kind, text=item.text, speaker=item.speaker, line_id=short,
                            delivery=item.delivery))
    envelope = scene.get("envelope_s")
    return SceneScript(blocks=blocks, cast=cast, place=Place(name=place, objects=objects),
                       envelope_s=float(envelope) if envelope else None), line_ids


def present(characters: list[Row], blocks: list[Block]) -> list[str]:
    """The people in the scene: those who speak, and those the script names (their name or an alias in a block)."""
    text = norm(" ".join(b.text for b in blocks))
    speakers = {norm(b.speaker) for b in blocks if b.speaker}
    out = []
    for c in characters:
        names = [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]]
        if any(norm(n) in speakers or (norm(n) and norm(n) in text) for n in names):
            out.append(str(c["name"]))
    known = {norm(n) for n in out}
    unlisted = {norm(b.speaker): b.speaker for b in blocks if b.speaker and norm(b.speaker) not in known}
    out += list(unlisted.values())
    return out


def objects_of(props: list[Row], location: Row | None, blocks: list[Block]) -> list[str]:
    """What the place has that a picture may show: the production's props the script or the location card names."""
    text = norm(" ".join(b.text for b in blocks) + " " + str(((location or {}).get("current") or {})
                                                            .get("card", {}).get("look") or ""))
    return [str(p["name"]) for p in props if norm(str(p.get("name") or "")) and norm(str(p["name"])) in text]


def context_of(scene: Row, episode: Row, before: str, after: str, cards: list[tuple[str, str]]) -> Row:
    return {"heading": str(scene.get("heading") or ""), "note": str(scene.get("note") or ""),
            "episode_title": str(episode.get("title") or ""), "episode": episode.get("number"),
            "synopsis": str(episode.get("synopsis") or ""),
            "before": before, "after": after,
            "characters": [{"name": n, "summary": s} for n, s in cards]}


# ── helpers over the code steps ──────────────────────────────────────────────────────────────────


def _step(ident: str) -> Any:
    return parts.step(ident, "step")


def _dump(value: Any) -> Any:
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value.model_dump(mode="json", by_alias=True)


def _refusals(fidelity: dict[str, Any], fit: dict[str, Any] | None = None,
              coverage: dict[str, Any] | None = None) -> str:
    rows = [f"[{b['code']}] {b['where']}: {b['reason']}" for b in fidelity.get("breaks") or []
            if b.get("fix") != "drop"]
    rows += [f"[{i['code']}] card {i.get('card') or '-'}: {i['message']}"
             for i in (fit or {}).get("issues") or [] if i.get("level") == "overrun"]
    rows += [f"[coverage] {h['why']}: give it a card ({h['suggest']})" for h in (coverage or {}).get("holes") or []]
    return "\n".join(rows)


def _glance(cards: list[ShotCard]) -> list[dict[str, Any]]:
    """Cards as the history keeps them: compact, enough to see what changed."""
    return [{"number": c.number, "moments": list(c.moments), "size": c.size, "arrangement": c.arrangement,
             "subject": c.subject, "take_s": c.take_s} for c in cards]


def _why_dropped(check: dict[str, Any], ident: str) -> str:
    return next((str(b.get("reason")) for b in check.get("breaks") or [] if b.get("moment") == ident
                 and b.get("reason")), "it invented story")


def _forget(analysis: SceneAnalysis, treatment: Treatment, gone: set[str]) -> tuple[SceneAnalysis, Treatment]:
    """The analysis and the treatment without a pointer at a moment that no longer exists."""
    def keep(ident: str) -> str:
        return "" if ident in gone else ident

    plant = (treatment.plant.model_copy(update={"plant_moment": keep(treatment.plant.plant_moment),
                                                "payoff_moment": keep(treatment.plant.payoff_moment)})
             if treatment.plant else None)
    brk = treatment.rhythm_break.model_copy(update={"moment": keep(treatment.rhythm_break.moment)}) \
        if treatment.rhythm_break else None
    treatment = treatment.model_copy(update={"plant": plant, "rhythm_break": brk,
                                             "ending_moment": keep(treatment.ending_moment)})
    pov = analysis.pov_owner.model_copy(update={"handover": keep(analysis.pov_owner.handover)})
    return analysis.model_copy(update={"pov_owner": pov}), treatment


def unbound(t: Treatment) -> Treatment:
    """A treatment as the director wrote it, before the moment writer bound ids to the plant, break and ending."""
    plant = t.plant.model_copy(update={"plant_moment": "", "payoff_moment": ""}) if t.plant else None
    brk = t.rhythm_break.model_copy(update={"moment": ""}) if t.rhythm_break else None
    return t.model_copy(update={"plant": plant, "rhythm_break": brk, "ending_moment": ""})


def facts_of(script: SceneScript) -> str:
    """What code already knows about the scene's clock, in words, so the model does not work it out in its reasoning
    (plan/2026-11-05 L2): each line's words, the seconds it takes to say, and the shortest Veo take that holds it
    alone."""
    takes = sorted(int(t) for t in VEO_DURATIONS)
    rows, spoken = [], 0.0
    for b in script.lines:
        words = words_in(b.text)
        said = speech_seconds(words, b.delivery)
        spoken += said
        take = next((t for t in takes if t >= said + LEAD_IN_S + TAIL_S - 1e-9), None)
        fits = (f"the shortest take that holds it alone: {take} s" if take else
                f"it does not fit one {takes[-1]} s take alone: it will be reported, never trimmed")
        rows.append(f"{b.line_id} ({b.speaker}, block {b.index}): {words} words, {said:.1f} s to say; {fits}")
    dialogue = [f"b{b.index}" for b in script.blocks if b.is_line]
    action = [f"b{b.index}" for b in script.blocks if not b.is_line]
    return "\n".join([
        f"Veo takes are {', '.join(str(t) for t in takes)} s and no other length. Speech runs at "
        f"{WORDS_PER_SECOND:g} words a second (slower for a whispered or halting delivery). A take with speech needs "
        f"{LEAD_IN_S:g} s before the first word, {LINE_GAP_S:g} s between two lines and {TAIL_S:g} s after the last.",
        f"Dialogue blocks: {', '.join(dialogue) or 'none'}. Action blocks: {', '.join(action) or 'none'}. "
        f"The lines take {spoken:.1f} s to say in all.", *rows])


def removed_lines(removed: list[Removed]) -> list[str]:
    """Elaborations a person took out, in words, for the take to leave out (the same addition never comes back)."""
    return [f"no {r.kind} serving blocks {', '.join(f'b{b}' for b in r.blocks) or '-'}"
            + (f" (it showed: {r.seen})" if r.seen else "") for r in removed]


@dataclass
class Draft:
    """One take, built into the plan's parts and checked by code."""

    analysis: SceneAnalysis
    treatment: Treatment
    alternates: list[Treatment]
    moments: list[Moment]
    staging: Staging
    cards: list[ShotCard]
    created: list[str]  # every moment the take wrote
    dropped: list[dict[str, str]]  # added moments fidelity dropped, with the reason
    gone: list[str]  # moments a person had removed before
    fidelity: dict[str, Any]
    fit: dict[str, Any]
    mends: list[str]

    @property
    def breaks(self) -> int:
        return int(self.fidelity["counts"]["breaks"])

    @property
    def overruns(self) -> int:
        return int(self.fit["overruns"])


# ── the pipeline ─────────────────────────────────────────────────────────────────────────────────


class Planner:
    def __init__(self, ctx: RunContext, script: SceneScript, *, context: Row, line_ids: dict[str, str],
                 removed: list[Removed], screening: bool = True, editorial: bool = False) -> None:
        self.ctx, self.script, self.context, self.line_ids = ctx, script, context, line_ids
        self.removed, self.screening = removed, screening
        self.devices = ""
        self.editorial = editorial  # the final cut trims takes: cards get a kept part (Phase 9)
        # the take is given the clock's facts (plan/2026-11-05 L2); the spike turns it off to measure it
        self.facts = True
        self.scene = _dump(script)
        self.log: list[str] = []
        self.report: dict[str, Any] = {}
        self.panel = parts.module("panel", "adam_screening", "graph")
        self.events: list[dict[str, Any]] = []  # report.history.events: append-only within a job
        self.first: dict[str, Any] = {}  # the plan as it entered screening, compact
        self.trace: dict[str, Any] = {"created": [], "dropped_fidelity": [], "removed_by_person": []}

    def ask(self, agent_id: str, inp: dict[str, Any]) -> Any:
        try:
            return agents.build(agent_id).run(inp, self.ctx)
        except Exception as exc:
            _log.warning("%s failed", agent_id, exc_info=True)
            raise Failed(f"{agent_id} could not answer ({type(exc).__name__}). Try again, or use the classic planner "
                         "for this scene.") from exc

    def passages(self, kind: str, query: str) -> str:
        found = _step("adam_passages").run({"kind": kind, "query": query})
        self.report.setdefault("passages", {})[kind] = found["sources"]
        return str(found["text"])

    @staticmethod
    def device_query(a: SceneAnalysis) -> str:
        return " ".join([a.about, a.dramatic_question, a.tone, a.value.start, a.value.end,
                         *[s.behaviour or s.object or s.sound for s in a.subtext]])

    # ① analyse ② conceive ──────────────────────────────────────────────────────────────────────

    def think(self, stance: str, resume: StoredPlan | None) -> tuple[SceneAnalysis, list[Treatment], int, str]:
        """-> (analysis, the three treatments, the index in use, who chose)."""
        if resume is not None and resume.alternates:
            analysis = resume.analysis.model_copy(update={"pov_owner": resume.analysis.pov_owner.model_copy(
                update={"handover": ""})})
            found = {t.stance: unbound(t) for t in [resume.treatment, *resume.alternates]}
            treatments = [found[s] for s in STANCES if s in found]
            self.log.append("the analysis and the treatments are kept; only the cards are planned again")
            self.devices = self.passages("devices", self.device_query(analysis))
        else:
            grammar = self.passages("grammar", self.script.listing()[:1200])
            analysis = self.ask("adam_dramaturg", {"scene": self.scene, "context": self.context,
                                                   "grammar": grammar}).analysis()
            devices = self.devices = self.passages("devices", self.device_query(analysis))
            treatments = self.ask("adam_director", {
                "scene": self.scene, "analysis": _dump(analysis), "before": self.context.get("before", ""),
                "after": self.context.get("after", ""), "devices": devices,
                "episode": self.context.get("episode")}).all()
        if not treatments:
            raise Failed("The director wrote no treatment for this scene.")
        distinct = _step("adam_distinct").run({"treatments": _dump(treatments), "analysis": _dump(analysis)})
        self.report["treatments"] = {"distinct": {"ok": distinct["ok"], "issues": distinct["issues"]},
                                     "scores": distinct["choice"]["scores"]}
        wanted = next((i for i, t in enumerate(treatments) if stance and norm(t.stance) == norm(stance)), None)
        if wanted is not None:
            return analysis, treatments, wanted, "person"
        return analysis, treatments, int(distinct["choice"]["index"] or 0), "score"

    # ③ imagine ─────────────────────────────────────────────────────────────────────────────────

    def imagine(self, analysis: SceneAnalysis, chosen: Treatment) -> tuple[list[Moment], SceneAnalysis, Treatment]:
        notes = ""
        for attempt in (1, 2):  # the second is the one retry, with the reasons
            out = self.ask("adam_moment_writer", {"scene": self.scene, "analysis": _dump(analysis),
                                                  "treatment": _dump(chosen), "notes": notes})
            moments = out.moment_list()
            self.trace["created"] = [m.id for m in moments]
            bound_analysis, bound = out.bind(analysis, chosen)
            left = _step("adam_write").run({"moments": _dump(moments), "removed": _dump(self.removed)})
            moments, gone = [Moment.model_validate(m) for m in left["moments"]], left["dropped"]
            check = _step("adam_fidelity").run({"scene": self.scene, "moments": _dump(moments)})
            if not check["send_back"]:
                break
            notes = _refusals(check)
            self.log.append(f"the moments were sent back once: {notes.splitlines()[0]}")
            if attempt == 2:
                raise Failed("The moments broke the script even after being sent back: " + notes.splitlines()[0])
        drop = set(check["dropped"]) | set(gone)
        self.trace["dropped_fidelity"] = [{"id": i, "reason": _why_dropped(check, i)} for i in check["dropped"]]
        self.trace["removed_by_person"] = sorted(gone)
        if check["dropped"]:
            self.log.append(f"{len(check['dropped'])} added moment(s) dropped: they invented story")
        self.report["moments"] = {"dropped": sorted(check["dropped"]), "removed_by_a_person": sorted(gone)}
        moments = [m for m in moments if m.id not in drop]
        analysis_b, bound = _forget(bound_analysis, bound, drop)
        return moments, analysis_b, bound

    # ④ stage ⑤ design ──────────────────────────────────────────────────────────────────────────

    def design(self, analysis: SceneAnalysis, treatment: Treatment, moments: list[Moment]
               ) -> tuple[Staging, list[ShotCard], SoundMap]:
        base = {"scene": self.scene, "analysis": _dump(analysis), "treatment": _dump(treatment),
                "moments": _dump(moments)}
        staging = self.ask("adam_blocker", base).staging()
        best: tuple[tuple[int, int, int], list[ShotCard]] | None = None
        notes = ""
        for _ in (1, 2):  # the second is the one retry, with the reasons
            cards = self.ask("adam_shot_designer", {**base, "staging": _dump(staging), "notes": notes,
                                                    "devices": self.devices,
                                                    "required": self.required(analysis, treatment),
                                                    "episode": self.context.get("episode")}).card_list()
            plan = {"analysis": _dump(analysis), "treatment": _dump(treatment), "moments": _dump(moments),
                    "staging": _dump(staging), "cards": _dump(cards)}
            fidelity = _step("adam_fidelity").run({"scene": self.scene, "plan": plan})
            fit = _step("adam_fit").run({"scene": self.scene, "plan": plan})
            if not fidelity["counts"]["breaks"] and fit["overruns"]:
                cards, fit = self.mend(treatment, moments, cards, fit)  # a crowded card is repaired in code first (F4)
                plan["cards"] = _dump(cards)
            seen = _step("adam_coverage").run({"scene": self.scene, "plan": plan})  # a hole is a send-back (F2)
            rank = (int(fidelity["counts"]["breaks"]), int(fit["overruns"]), len(seen["holes"]))
            if best is None or rank < best[0]:
                best = (rank, cards)
            if rank == (0, 0, 0):
                break
            notes = _refusals(fidelity, fit, seen)
            self.events.append({"stage": "design", "kind": "sent_back", "why": notes.splitlines(),
                                "cards": _glance(cards)})
            self.log.append(f"the cards were sent back once: {notes.splitlines()[0]}")
        assert best is not None
        (breaks, overruns, holes), cards = best
        if breaks:
            raise Failed("The cards broke the script even after being sent back (a line or a moment is missing or "
                         "out of order).")
        if overruns:
            self.log.append(f"{overruns} overrun(s) remain: reported, never trimmed")
        if holes:
            self.log.append(f"{holes} required face(s) are still not seen: reported, screening is asked to mend it")
        sound = self.ask("adam_sound_designer", {"scene": self.scene, "treatment": _dump(treatment),
                                                 "moments": _dump(moments), "cards": _dump(cards)})
        return staging, sound.apply(cards), sound.sound_map()

    def required(self, analysis: SceneAnalysis, treatment: Treatment) -> list[str]:
        """The faces the analysis says must be seen, in words: what the designer is told to meet (F2)."""
        found = _step("adam_coverage").run({"scene": self.scene, "analysis": _dump(analysis),
                                            "treatment": _dump(treatment)})
        return [str(line) for line in found.get("required") or []]

    def mend(self, treatment: Treatment, moments: list[Moment], cards: list[ShotCard], fit: dict[str, Any]
             ) -> tuple[list[ShotCard], dict[str, Any]]:
        """Split or lengthen a crowded card by code; -> (the cards, the fit report of them)."""
        mended = _step("adam_split").run({"scene": self.scene, "moments": _dump(moments), "cards": _dump(cards),
                                          "treatment": _dump(treatment)})
        if not mended["changed"]:
            return cards, fit
        cards = [ShotCard.model_validate(c) for c in mended["cards"]]
        self.events.append({"stage": "design", "kind": "split", "splits": mended["splits"], "cards": _glance(cards)})
        self.log.append("a crowded card was repaired in code: " + "; ".join(
            f"card {s['card']} {s['how']} ({' + '.join(str(t) for t in s['takes'])} s)" for s in mended["splits"]))
        return cards, _step("adam_fit").run({"scene": self.scene, "moments": _dump(moments), "cards": _dump(cards)})

    # ⑥ screen and the report ───────────────────────────────────────────────────────────────────

    def screen(self, plan: AdamPlan) -> tuple[AdamPlan, list[str]]:
        """-> (the plan to keep, the critics' notes). The first plan stands if the panel fails or nothing is better."""
        kit = PanelKit(self.panel.ID, self.ctx)
        first = _dump(plan)
        shown: dict[str, Any] = {"ran": False}
        try:
            out = self.panel.build(self.ctx).invoke({"brief": {"scene": self.scene}, "candidates": [first],
                                                     "lenses": self.panel.lenses(kit)})
        except Exception:
            _log.warning("screening failed; the first plan stands", exc_info=True)
            self.report["screening"] = shown
            return plan, []
        winner = out["candidates"][out["winner"]]
        scores = {r["lens"]: r["score"] for r in out.get("results") or [] if r}
        revision = (out["candidates"][1].get("report") or {}).get("revision") if len(out["candidates"]) > 1 else None
        kept = "revision" if out["winner"] else "first"
        shown.update(ran=True, scores=scores, notes=list(out.get("notes") or []), revised=len(out["candidates"]) > 1,
                     kept=kept, error=out.get("error", ""), revision=revision)
        self.report["screening"] = shown
        self.events += self.screened(kit, out, revision, kept)
        if revision and revision.get("invalid"):
            self.log.append("the revision did not stand (" + revision["invalid"][0] + "): the first plan is kept")
        elif out["winner"]:
            self.log.append("the revision after screening scored better and was kept")
        return AdamPlan.model_validate(winner), list(out.get("notes") or [])

    def screened(self, kit: PanelKit, out: dict[str, Any], revision: dict[str, Any] | None, kept: str
                 ) -> list[dict[str, Any]]:
        """What screening did, for the plan log: the notes, the revision (each operation, the note it answered, any
        reason it did not stand) and how the two plans ranked."""
        judge = parts.module("step", "adam_score", "logic")
        events: list[dict[str, Any]] = [{"stage": "screening", "kind": "notes", "notes":
                                         _step("adam_notes").run({"results": out.get("results") or []})["kept"]}]
        if revision:
            events.append({"stage": "screening", "kind": "revision", **{k: revision.get(k) for k in (
                "ops", "ledger", "invalid", "splits", "unsplit", "dropped", "skipped")}})
        evals = [self.panel.evaluate(kit, self.scene, c) for c in out["candidates"]]
        lost = judge.lost_cells([e["score"] for e in evals])
        rows = [{"which": "first" if i == 0 else "revision", "rank": list(judge.rank(e["score"], lost[i])),
                 "percent": e["score"]["percent"], "coverage": e["score"].get("coverage"), "cards": len(c["cards"]),
                 "moments": len(c["moments"]), "lost_cells": lost[i]}
                for i, (e, c) in enumerate(zip(evals, out["candidates"], strict=True))]
        events.append({"stage": "screening", "kind": "kept", "which": kept, "candidates": rows})
        return events

    def reconcile(self, plan: AdamPlan) -> dict[str, Any]:
        """Every moment the writer made ends in exactly one bucket (F1); one with no record fails the scene."""
        screening = self.report.get("screening") or {}
        revision = screening.get("revision") if screening.get("kept") == "revision" else None
        by_op = [{"id": o["target"], "op": f"operation {o['n']} ({o['op']})", "note_id": o.get("note_id") or ""}
                 for o in (revision or {}).get("ops") or [] if o["op"] == "remove_moment" and o["applied"]]
        from_revision = [{"id": i, "reason": "the revision invented story"}
                         for i in (revision or {}).get("dropped") or []]
        inputs = {"created": self.trace["created"], "final": [m.id for m in plan.moments],
                  "dropped_fidelity": [*self.trace["dropped_fidelity"], *from_revision],
                  "removed_by_person": self.trace["removed_by_person"], "removed_by_operation": by_op}
        found = _step("adam_ledger").run(inputs)
        self.report["ledger"] = {**found, "inputs": inputs}
        if not found["ok"]:
            raise Failed(f"Shot Planner Adam lost track of the plan ({found['problems'][0]}). Try again, or use the "
                         "classic planner for this scene.")
        return found

    def finish(self, plan: AdamPlan, *, analysis: SceneAnalysis, treatments: list[Treatment], index: int,
               chosen_by: str, previous: dict[str, Any], notes: list[str], job_id: str) -> Planned:
        kit = PanelKit(self.panel.ID, self.ctx)
        ev = self.panel.evaluate(kit, self.scene, _dump(plan))
        fit, score = ev["fit"], ev["score"]
        self.reconcile(plan)
        asked: list[dict[str, Any]] = [{"question": q.question, "blocks": q.blocks, "source": q.source}
                                       for q in plan.analysis.questions]
        asked += [{"question": q["question"], "blocks": q["blocks"], "source": "continuity"}
                  for q in ev["continuity"].get("questions") or []
                  if not any(q["object"] in str(a["question"]).lower() for a in asked)]
        self.report.update(
            questions=asked,
            coverage={k: ev["coverage"].get(k) for k in ("required", "filled", "coverage", "holes", "grid", "cells")},
            history={"first": self.first, "events": self.events},
            fidelity={"ok": ev["fidelity"].get("ok"), "counts": ev["fidelity"].get("counts"),
                      "breaks": ev["fidelity"].get("breaks")},
            fit={"runtime_s": fit.get("runtime_s"), "envelope_s": fit.get("envelope_s"),
                 "over_envelope_s": fit.get("over_envelope_s"), "overruns": fit.get("overruns"),
                 "issues": fit.get("issues")},
            continuity={"count": ev["continuity"].get("count"), "issues": ev["continuity"].get("issues")},
            feasibility={"unaddressed": ev["feasibility"].get("unaddressed"),
                         "flags": [f for f in ev["feasibility"].get("flags") or [] if not f.get("addressed")]},
            score={"percent": score.get("percent"), "score": score.get("score"), "max": score.get("max"),
                   "craft_percent": score.get("craft_percent"), "coverage": score.get("coverage"),
                   "loss": score.get("loss"), "loss_reasons": score.get("loss_reasons"),
                   "signals": [{"signal": s["signal"], "applicable": s["applicable"], "weight": s["weight"],
                                "points": s["points"]} for s in score.get("signals") or []]},
            log=self.log)
        n = len(plan.cards) or 1  # density is measured, not targeted: ASL alone is the wrong single number (F6)
        self.report["density"] = {"cards": len(plan.cards), "moments": len(plan.moments),
                                  "moments_per_card": round(len(plan.moments) / n, 2),
                                  "used_shot_length_s": round(float(fit.get("runtime_s") or 0) / n, 2)}
        chosen = plan.treatment
        others = [t for i, t in enumerate(treatments) if i != index]
        stored = StoredPlan(job_id=job_id, input_hash=self.input_hash(str(self.report.get("mode") or "staged")),
                            chosen=chosen.stance or treatments[index].stance, chosen_by=chosen_by,  # type: ignore[arg-type]
                            analysis=plan.analysis, treatment=chosen, alternates=others, moments=plan.moments,
                            staging=plan.staging, cards=plan.cards, sound_map=plan.sound_map, removed=self.removed,
                            line_ids=self.line_ids, report=self.report, previous=previous)
        return Planned(stored=stored, fit=fit, notes=notes, log=self.log)

    # ── a whole scene ───────────────────────────────────────────────────────────────────────────

    def plan(self, *, stance: str = "", resume: StoredPlan | None = None, previous: dict[str, Any] | None = None,
             job_id: str = "") -> Planned:
        analysis, treatments, index, chosen_by = self.think(stance, resume)
        moments, analysis, bound = self.imagine(analysis, treatments[index])
        staging, cards, sound_map = self.design(analysis, bound, moments)
        if self.editorial:
            trimmed = _step("adam_trim").run({"cards": _dump(cards)})
            cards = [ShotCard.model_validate(c) for c in trimmed["cards"]]
            self.log += trimmed["notes"]
            self.report["editorial"] = {"saved_s": trimmed["saved_s"], "notes": trimmed["notes"]}
        plan = AdamPlan(analysis=analysis, treatment=bound, moments=moments, staging=staging, cards=cards,
                        sound_map=sound_map, report={"editorial": True} if self.editorial else {})
        notes: list[str] = []
        self.first = {"cards": _glance(cards), "moments": [m.id for m in moments]}
        if self.screening:
            plan, notes = self.screen(plan)
        else:
            self.report["screening"] = {"ran": False}
        return self.finish(plan, analysis=plan.analysis, treatments=treatments, index=index, chosen_by=chosen_by,
                           previous=previous or {}, notes=notes, job_id=job_id)

    # ── plan/2026-11-05: the scene in one take ───────────────────────────────────────────────────

    def input_hash(self, mode: str) -> str:
        """A hash of everything Adam is given for this scene (plan/2026-11-05 L5): a rebuild whose hash is unchanged
        keeps
        the plan a person already saw. It holds the script and its context, the real line ids, the elaborations a person
        took out, whether screening runs, the editorial setting and the mode (the two modes plan differently)."""
        payload = {"scene": self.scene, "context": self.context, "line_ids": self.line_ids,
                   "removed": [r.model_dump() for r in self.removed], "screening": self.screening,
                   "editorial": self.editorial, "mode": mode}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
                              .encode("utf-8")).hexdigest()[:16]

    def ask_take(self, inp: dict[str, Any]) -> Any:
        """The take, with one retry after a short wait when the call could not be made (plan/2026-11-05 R3)."""
        try:
            return self.ask("adam_take", inp)
        except Failed:
            self.log.append("the take could not be made; asking once more")
            time.sleep(TAKE_BACKOFF_S)
            return self.ask("adam_take", inp)

    def draft(self, base: dict[str, Any], notes: str, given: SceneAnalysis | None, stance: str) -> Draft:
        """One take, built into the plan's parts: the moments a person removed or fidelity refuses are taken out (and
        out of the cards and the staging), a script line goes to the card that shows its moment (rung 0), and a crowded
        card is repaired in code. Whether it broke the script is for the caller."""
        out = self.ask_take({**base, "notes": notes})
        built = out.plan(analysis=given, stance=stance)
        created = [m.id for m in built.moments]
        left = _step("adam_write").run({"moments": _dump(built.moments), "removed": _dump(self.removed)})
        moments, gone = [Moment.model_validate(m) for m in left["moments"]], list(left["dropped"])
        check = _step("adam_fidelity").run({"scene": self.scene, "moments": _dump(moments)})
        drop = set(check["dropped"]) | set(gone)
        dropped = [{"id": i, "reason": _why_dropped(check, i)} for i in check["dropped"]]
        analysis, treatment, staging, cards = built.analysis, built.treatment, built.staging, built.cards
        if drop:
            moments, cards, _ = drop_moments(moments, cards, drop)
            staging = staging.model_copy(update={"marks": [m for m in staging.marks if m.moment not in drop],
                                                 "moves": [m for m in staging.moves if m.moment not in drop]})
            analysis, treatment = _forget(analysis, treatment, drop)
        mended = _step("adam_problems").run({"scene": self.scene, "moments": _dump(moments), "cards": _dump(cards)})
        if mended["changed"]:
            cards = [ShotCard.model_validate(c) for c in mended["cards"]]
        plan = {"analysis": _dump(analysis), "treatment": _dump(treatment), "moments": _dump(moments),
                "staging": _dump(staging), "cards": _dump(cards)}
        fidelity = _step("adam_fidelity").run({"scene": self.scene, "plan": plan})
        fit = _step("adam_fit").run({"scene": self.scene, "plan": plan})
        if not fidelity["counts"]["breaks"] and fit["overruns"]:
            cards, fit = self.mend(treatment, moments, cards, fit)
        return Draft(analysis=analysis, treatment=treatment, alternates=built.alternates, moments=moments,
                     staging=staging, cards=cards, created=created, dropped=dropped, gone=gone, fidelity=fidelity,
                     fit=fit, mends=list(mended["mends"]))

    def plan_take(self, *, stance: str = "", resume: StoredPlan | None = None, previous: dict[str, Any] | None = None,
                  job_id: str = "") -> Planned:
        """The scene in one take: take → the sound → code → one critic → the fixer ladder → finish."""
        self.report["mode"] = "take"
        given = None
        if resume is not None:  # a treatment switch: the analysis is kept, the take is asked again with the new stance
            given = resume.analysis.model_copy(update={"pov_owner": resume.analysis.pov_owner.model_copy(
                update={"handover": ""})})
            self.log.append("the analysis is kept; the scene is taken again under the other treatment")
        query = self.device_query(given) if given else self.script.listing()[:1200]
        self.devices = self.passages("devices", query)
        base = {"scene": self.scene, "context": self.context, "devices": self.devices,
                "facts": facts_of(self.script) if self.facts else "",
                "grammar": "" if given else self.passages("grammar", self.script.listing()[:1200]),
                "removed": removed_lines(self.removed), "analysis": _dump(given) if given else None, "stance": stance}
        best: Draft | None = None
        notes = ""
        for _ in (1, 2):  # the second is the one send-back, with the reasons
            tried = self.draft(base, notes, given, stance)
            if best is None or (tried.breaks, tried.overruns) < (best.breaks, best.overruns):
                best = tried
            if not tried.breaks:
                break
            notes = _refusals(tried.fidelity, tried.fit)
            self.events.append({"stage": "take", "kind": "sent_back", "why": notes.splitlines(),
                                "cards": _glance(tried.cards)})
            self.log.append(f"the take was sent back once: {notes.splitlines()[0]}")
        assert best is not None
        if best.breaks:
            raise Failed("The take broke the script even after being sent back (a line or a moment is missing "
                         "or out of order).")
        self.trace = {"created": best.created, "dropped_fidelity": best.dropped, "removed_by_person": sorted(best.gone)}
        self.report["moments"] = {"dropped": sorted(d["id"] for d in best.dropped),
                                  "removed_by_a_person": sorted(best.gone)}
        if best.dropped:
            self.log.append(f"{len(best.dropped)} added moment(s) dropped: they invented story")
        if best.mends:
            self.events.append({"stage": "take", "kind": "mended", "mends": best.mends})
            self.log += [f"mended in code: {m}" for m in best.mends]
        if best.overruns:
            self.log.append(f"{best.overruns} overrun(s) remain: reported, never trimmed")
        sound = self.ask("adam_sound_designer", {"scene": self.scene, "treatment": _dump(best.treatment),
                                                 "moments": _dump(best.moments), "cards": _dump(best.cards)})
        cards = sound.apply(best.cards)
        if self.editorial:
            trimmed = _step("adam_trim").run({"cards": _dump(cards)})
            cards = [ShotCard.model_validate(c) for c in trimmed["cards"]]
            self.log += trimmed["notes"]
            self.report["editorial"] = {"saved_s": trimmed["saved_s"], "notes": trimmed["notes"]}
        plan = AdamPlan(analysis=best.analysis, treatment=best.treatment, moments=best.moments, staging=best.staging,
                        cards=cards, sound_map=sound.sound_map(), report={"editorial": True} if self.editorial else {})
        self.first = {"cards": _glance(cards), "moments": [m.id for m in best.moments]}
        self.events.append({"stage": "take", "kind": "written", "cards": _glance(cards),
                            "pitches": len(best.alternates)})
        heard: list[str] = []
        if self.screening:
            plan, heard = self.screen_take(plan)
        else:
            self.report["screening"] = {"ran": False}
        alternates = list(best.alternates)
        for old in [resume.treatment, *resume.alternates] if resume is not None else []:
            if old.stance != plan.treatment.stance and old.stance not in {a.stance for a in alternates}:
                alternates.append(old)  # the treatment just left stays one click away
        return self.finish(plan, analysis=plan.analysis, treatments=[plan.treatment, *alternates], index=0,
                           chosen_by="person" if stance else "model", previous=previous or {}, notes=heard,
                           job_id=job_id)

    def screen_take(self, plan: AdamPlan) -> tuple[AdamPlan, list[str]]:
        """One critic reads the plan in four lenses; code's faults and the critic's high notes become problems; the
        ladder fixes them one at a time. -> (the plan to keep, the critic's notes). The take's plan stands for anything
        that fails here."""
        kit = PanelKit(self.panel.ID, self.ctx)
        ev = self.panel.evaluate(kit, self.scene, _dump(plan))
        results: list[dict[str, Any]] = []
        error = ""
        try:
            report = _step("adam_notes").run({**{k: ev[k] for k in self.panel.REPORTS}, "score": ev["score"]})["text"]
            read = self.ask("adam_critic", {**{k: _dump(getattr(plan, k)) for k in (
                "analysis", "treatment", "moments", "staging", "cards", "sound_map")}, "scene": self.scene,
                "report": report})
            results = read.results({c.number for c in plan.cards})
        except Failed as failure:
            error = str(failure)
            self.log.append("the critic could not answer; the code's faults are still fixed")
        merged = _step("adam_notes").run({"results": results})
        sorted_ = _step("adam_problems").run({"reports": {k: ev[k] for k in ("fit", "coverage", "continuity",
                                                                              "feasibility")},
                                              "notes": merged["kept"]})
        problems = [Problem.model_validate(p) for p in sorted_["problems"]]
        self.events.append({"stage": "screening", "kind": "notes", "notes": merged["kept"]})
        ladder = Ladder(self.ctx, self.panel, self.scene, events=self.events)
        fixed = ladder.run(plan, problems) if problems else Fixed(plan=plan, outcomes=[])
        judge = parts.module("step", "adam_score", "logic")
        evals = [ev, ladder.evaluate(fixed.plan)] if fixed.changed else [ev]
        lost = judge.lost_cells([e["score"] for e in evals])
        ranks = [judge.rank(e["score"], lost[i]) for i, e in enumerate(evals)]
        worse = fixed.changed and ranks[1] > ranks[0]
        kept = "revision" if fixed.changed and not worse else "first"
        by_note = {o.problem.note_id: o for o in fixed.outcomes if o.problem.note_id}
        left_notes = {p["note_id"] for p in sorted_["left"] if p.get("note_id")}
        ledger = []
        for n in merged["kept"]:
            o = by_note.get(n["id"])
            declined = (f"not fixed: {o.reason}" if o is not None and not o.fixed else
                        "left over: the ladder works on a few problems a scene" if n["id"] in left_notes else "")
            ledger.append({**{k: n[k] for k in ("id", "lens", "severity", "kind", "card", "cell", "note")},
                           "done": list(o.ops) if o is not None and o.fixed else [], "declined": declined,
                           "answered": bool(o is not None or declined)})
        invalid = ["the fixes ranked the plan worse than the take's: the take's plan is kept"] if worse else []
        record = {"operations": len(fixed.ops), "skipped": fixed.skipped, "dropped": fixed.dropped, "ops": fixed.ops,
                  "ledger": ledger, "splits": fixed.splits, "unsplit": [], "invalid": invalid, "mode": "ladder",
                  "problems": [o.row() for o in fixed.outcomes], "left": sorted_["left"]}
        self.report["screening"] = {"ran": True, "scores": merged["scores"], "notes": list(merged["notes"]),
                                    "revised": fixed.changed, "kept": kept, "error": error,
                                    "revision": record if (fixed.outcomes or merged["kept"]) else None}
        self.report["fixer"] = {"problems": [o.row() for o in fixed.outcomes], "left": len(sorted_["left"]),
                                "counts": sorted_["counts"]}
        shown = [fixed.plan if i else plan for i in range(len(evals))]
        rows = [{"which": "first" if i == 0 else "revision", "rank": list(ranks[i]), "percent": e["score"]["percent"],
                 "coverage": e["score"].get("coverage"), "cards": len(shown[i].cards),
                 "moments": len(shown[i].moments), "lost_cells": lost[i]} for i, e in enumerate(evals)]
        self.events.append({"stage": "screening", "kind": "kept", "which": kept, "candidates": rows})
        if invalid:
            self.log.append(invalid[0])
        elif kept == "revision":
            self.log.append(f"{sum(o.fixed for o in fixed.outcomes)} of {len(fixed.outcomes)} problem(s) were fixed")
        return (fixed.plan if kept == "revision" else plan), list(merged["notes"])

    def remove_moment(self, stored: StoredPlan, moment_id: str, job_id: str = "") -> Planned:
        """A person took an elaboration out: the moment and any card left with nothing go, the sound map follows, the
        code reports are made again. No model is called, and the same addition never comes back (`removed`)."""
        found = stored.moment(moment_id)
        if found is None:
            raise Failed(f"This scene's plan has no moment {moment_id}.")
        if found.tier == "script":
            raise Failed("A moment that presents the script cannot be removed.")
        self.removed = [*stored.removed, Removed.of(found)]
        before = (stored.report.get("ledger") or {}).get("inputs") or {}
        self.trace = {"created": list(before.get("created") or [m.id for m in stored.moments]),
                      "dropped_fidelity": list(before.get("dropped_fidelity") or []),
                      "removed_by_person": [*(before.get("removed_by_person") or []), moment_id]}
        history = stored.report.get("history") or {}
        self.first, self.events = dict(history.get("first") or {}), list(history.get("events") or [])
        self.events.append({"stage": "person", "kind": "removed", "moment": moment_id, "what": found.kind,
                            "cards": len(stored.cards)})
        moments, cards, numbers = drop_moments(stored.moments, stored.cards, {moment_id})
        analysis, treatment = _forget(stored.analysis, stored.treatment, {moment_id})
        sound = remap_sound(stored.sound_map, numbers, {m.id for m in moments})
        plan = AdamPlan(analysis=analysis, treatment=treatment, moments=moments, staging=stored.staging, cards=cards,
                        sound_map=sound, report={"editorial": True} if self.editorial else {})
        self.report = {**stored.report, "removed": [f"{r.kind} {r.seen}".strip() for r in self.removed]}
        self.log = [f"{moment_id} removed by a person; {len(stored.cards) - len(cards)} card(s) went with it"]
        stages = [stored.treatment, *stored.alternates]
        return self.finish(plan, analysis=analysis, treatments=stages, index=0, chosen_by=stored.chosen_by,
                           previous=stored.previous, notes=[], job_id=job_id)
