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
planner is the way out (plan §5.5: Adam has no rules fallback worth having). Overruns are REPORTED, never trimmed.

Pure orchestration over the agents and steps by id: no database here. The caller (graph.py) reads the rows and
writes them.
"""
from __future__ import annotations

import logging
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
from contracts.adam.screening import drop_moments, remap_sound
from contracts.adam.stored import Removed, StoredPlan
from contracts.adam.wire import STANCES
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext
from hiru_ai.core.panels import PanelKit

_log = logging.getLogger(__name__)
Row = dict[str, Any]
NO_MODEL = "Shot Planner Adam needs the AI model, which is not available. Use the classic planner for this scene."


class Failed(Exception):
    """The scene could not be planned; the message says why, in words a person reads."""


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
            "episode_title": str(episode.get("title") or ""), "synopsis": str(episode.get("synopsis") or ""),
            "before": before, "after": after,
            "characters": [{"name": n, "summary": s} for n, s in cards]}


# ── helpers over the code steps ──────────────────────────────────────────────────────────────────


def _step(ident: str) -> Any:
    return parts.step(ident, "step")


def _dump(value: Any) -> Any:
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value.model_dump(mode="json", by_alias=True)


def _refusals(fidelity: dict[str, Any], fit: dict[str, Any] | None = None) -> str:
    rows = [f"[{b['code']}] {b['where']}: {b['reason']}" for b in fidelity.get("breaks") or []
            if b.get("fix") != "drop"]
    rows += [f"[{i['code']}] card {i.get('card') or '-'}: {i['message']}"
             for i in (fit or {}).get("issues") or [] if i.get("level") == "overrun"]
    return "\n".join(rows)


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


# ── the pipeline ─────────────────────────────────────────────────────────────────────────────────


class Planner:
    def __init__(self, ctx: RunContext, script: SceneScript, *, context: Row, line_ids: dict[str, str],
                 removed: list[Removed], screening: bool = True, editorial: bool = False) -> None:
        self.ctx, self.script, self.context, self.line_ids = ctx, script, context, line_ids
        self.removed, self.screening = removed, screening
        self.devices = ""
        self.editorial = editorial  # the final cut trims takes: cards get a kept part (Phase 9)
        self.scene = _dump(script)
        self.log: list[str] = []
        self.report: dict[str, Any] = {}
        self.panel = parts.module("panel", "adam_screening", "graph")

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
                "after": self.context.get("after", ""), "devices": devices}).all()
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
        best: tuple[tuple[int, int], list[ShotCard]] | None = None
        notes = ""
        for _ in (1, 2):  # the second is the one retry, with the reasons
            cards = self.ask("adam_shot_designer", {**base, "staging": _dump(staging), "notes": notes,
                                                    "devices": self.devices}).card_list()
            plan = {"analysis": _dump(analysis), "treatment": _dump(treatment), "moments": _dump(moments),
                    "staging": _dump(staging), "cards": _dump(cards)}
            fidelity = _step("adam_fidelity").run({"scene": self.scene, "plan": plan})
            fit = _step("adam_fit").run({"scene": self.scene, "plan": plan})
            rank = (int(fidelity["counts"]["breaks"]), int(fit["overruns"]))
            if best is None or rank < best[0]:
                best = (rank, cards)
            if rank == (0, 0):
                break
            notes = _refusals(fidelity, fit)
            self.log.append(f"the cards were sent back once: {notes.splitlines()[0]}")
        assert best is not None
        (breaks, overruns), cards = best
        if breaks:
            raise Failed("The cards broke the script even after being sent back (a line or a moment is missing or "
                         "out of order).")
        if overruns:
            self.log.append(f"{overruns} overrun(s) remain: reported, never trimmed")
        sound = self.ask("adam_sound_designer", {"scene": self.scene, "treatment": _dump(treatment),
                                                 "moments": _dump(moments), "cards": _dump(cards)})
        return staging, sound.apply(cards), sound.sound_map()

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
        shown.update(ran=True, scores=scores, notes=list(out.get("notes") or []), revised=len(out["candidates"]) > 1,
                     kept="revision" if out["winner"] else "first", error=out.get("error", ""),
                     revision=(winner.get("report") or {}).get("revision") if out["winner"] else None)
        self.report["screening"] = shown
        if out["winner"]:
            self.log.append("the revision after screening scored better and was kept")
        return AdamPlan.model_validate(winner), list(out.get("notes") or [])

    def finish(self, plan: AdamPlan, *, analysis: SceneAnalysis, treatments: list[Treatment], index: int,
               chosen_by: str, previous: dict[str, Any], notes: list[str], job_id: str) -> Planned:
        kit = PanelKit(self.panel.ID, self.ctx)
        ev = self.panel.evaluate(kit, self.scene, _dump(plan))
        fit, score = ev["fit"], ev["score"]
        self.report.update(
            fidelity={"ok": ev["fidelity"].get("ok"), "counts": ev["fidelity"].get("counts"),
                      "breaks": ev["fidelity"].get("breaks")},
            fit={"runtime_s": fit.get("runtime_s"), "envelope_s": fit.get("envelope_s"),
                 "over_envelope_s": fit.get("over_envelope_s"), "overruns": fit.get("overruns"),
                 "issues": fit.get("issues")},
            continuity={"count": ev["continuity"].get("count"), "issues": ev["continuity"].get("issues")},
            feasibility={"unaddressed": ev["feasibility"].get("unaddressed"),
                         "flags": [f for f in ev["feasibility"].get("flags") or [] if not f.get("addressed")]},
            score={"percent": score.get("percent"), "score": score.get("score"), "max": score.get("max"),
                   "loss": score.get("loss"), "loss_reasons": score.get("loss_reasons"),
                   "signals": [{"signal": s["signal"], "applicable": s["applicable"], "weight": s["weight"],
                                "points": s["points"]} for s in score.get("signals") or []]},
            log=self.log)
        chosen = plan.treatment
        others = [t for i, t in enumerate(treatments) if i != index]
        stored = StoredPlan(job_id=job_id, chosen=chosen.stance or treatments[index].stance, chosen_by=chosen_by,  # type: ignore[arg-type]
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
        if self.screening:
            plan, notes = self.screen(plan)
        else:
            self.report["screening"] = {"ran": False}
        return self.finish(plan, analysis=plan.analysis, treatments=treatments, index=index, chosen_by=chosen_by,
                           previous=previous or {}, notes=notes, job_id=job_id)

    def remove_moment(self, stored: StoredPlan, moment_id: str, job_id: str = "") -> Planned:
        """A person took an elaboration out: the moment and any card left with nothing go, the sound map follows, the
        code reports are made again. No model is called, and the same addition never comes back (`removed`)."""
        found = stored.moment(moment_id)
        if found is None:
            raise Failed(f"This scene's plan has no moment {moment_id}.")
        if found.tier == "script":
            raise Failed("A moment that presents the script cannot be removed.")
        self.removed = [*stored.removed, Removed.of(found)]
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
