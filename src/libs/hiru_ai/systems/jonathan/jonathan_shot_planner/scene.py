"""One scene through Shot Planner Jonathan (plan/2026-11-06b §3, §4.3): the cinematic lab's stabiliser, in the product.

    pack      jonathan_pack (code)      the author's input, built from the database's rows
    author    jonathan_author           ONE call, as a production team: the treatment, the sequences, every shot with
    its
                                        camera design, what was added, the staging and the end state
    mend      jonathan_mend (code)      a longer take, a cut at a block boundary with each part's own beats, speech out
    of
                                        free text, the seconds a line keeps, the numbering, the end state's places
    check     jonathan_check (code)     every fact (a problem: an exact sentence and who fixes it) and the craft
    measures;
                                        the plan's SCORE is (faults, craft gaps), lower is better
    revise    jonathan_revise           only while a fault or a craft gap is left: the author's own prompt and message,
                                        its BEST plan so far and what code found → the whole corrected plan; mended and
                                        checked again; at most `MAX_REVISES` passes; a worse pass is never built on, and
                                        the best plan is kept
    seam      jonathan_seams (code)     a linked scene's opening against the end state of the scene before; at most one
                                        more revise for it

A scene whose draft is clean makes ONE model call; the lab's evidence is one to three a scene. A scene is never failed
for what is left: it is reported. It fails only when there is no usable plan (no model, or the author's answer unusable
twice), and the classic planner is the way out.

Pure orchestration over the agents and steps by id: no database here. The caller (graph.py) reads the rows and writes
them.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from contracts import sceneplan
from contracts.jonathan.checks import faults
from contracts.jonathan.measures import Craft, Measure, missed
from contracts.jonathan.plan import Problem, norm
from contracts.jonathan.scene import BlockS, PlaceS, SceneS, plain_name
from contracts.jonathan.stored import Link, LookChange, Removed, StoredPlan
from contracts.jonathan.wire import AddedW, EndStateW, JonathanWire
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext

_log = logging.getLogger(__name__)
Row = dict[str, Any]
NO_MODEL = "Shot Planner Jonathan needs the AI model, which is not available. Use the classic planner for this scene."
BACKOFF_S = 2.0  # the wait before the one retry of an author call that could not be made
MAX_REVISES = 2  # the lab: a second pass converges; a third is not worth paying for


class Failed(Exception):
    """The scene could not be planned; the message says why, in words a person reads."""


@dataclass
class Unchanged:
    """A scene whose input is the one its stored plan was made from: it is kept as it is (plan §4.3)."""

    stored: StoredPlan


@dataclass
class Planned:
    stored: StoredPlan
    changed_end: bool = True  # its end state differs from the one stored before: the scenes after it may be out of date
    log: list[str] = field(default_factory=list)


@dataclass
class Judged:
    """A plan as code mended and judged it."""

    plan: JonathanWire
    problems: list[Problem]  # everything the checks found (faults and reports)
    measures: list[Measure]
    dropped: list[Problem]  # additions the mend took out
    extra: list[Problem] = field(default_factory=list)  # problems from outside the plan's checks (a seam)
    mended: list[str] = field(default_factory=list)  # what code fixed in it, in sentences

    @property
    def faults(self) -> list[Problem]:
        return [*faults(self.problems), *self.extra]

    @property
    def gaps(self) -> list[Measure]:
        return missed(self.measures)

    @property
    def score(self) -> tuple[int, int]:
        """Lower is better: hard faults first, then craft gaps (the lab's `score`). A taste judgement is a person's."""
        return len(self.faults), len(self.gaps)


# ── the scene, as Jonathan is given it ──────────────────────────────────────────────────────────────


def script_of(scene: Row, lines: list[Row], *, cast: list[str], others: list[str], place: str, objects: list[str]
              ) -> tuple[SceneS, dict[str, str]]:
    """The scene's blocks as `SceneS` (with the time its reading gives them), and the map from the short line id the
    author sees (L<block>) to the dialogue line's real id."""
    items = sceneplan.scene_items(scene, lines)
    line_ids: dict[str, str] = {}
    blocks = []
    for item in items:
        block = BlockS.of(item)
        if item.is_line:
            short = f"L{item.index}"  # the line at block 4 is L4: the id says where the line is
            line_ids[short] = str(item.line_id)
            block = block.model_copy(update={"line_id": short})
        blocks.append(block)
    envelope = scene.get("envelope_s")
    return SceneS(blocks=blocks, cast=cast, others=others, place=PlaceS(name=place, objects=objects),
                  envelope_s=float(envelope) if envelope else None), line_ids


def present(characters: list[Row], blocks: list[BlockS]) -> list[str]:
    """The people in the scene: those who speak, and those the script names (their name or an alias in a block)."""
    text = norm(" ".join(b.text for b in blocks))
    speakers = {norm(plain_name(b.speaker)) for b in blocks if b.speaker}
    out = []
    for c in characters:
        names = [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]]
        if any(norm(n) in speakers or (norm(n) and norm(n) in text) for n in names):
            out.append(str(c["name"]))
    known = {norm(n) for n in out}
    unlisted = {norm(plain_name(b.speaker)): plain_name(b.speaker) for b in blocks
                if b.speaker and norm(plain_name(b.speaker)) not in known}
    return out + list(unlisted.values())


def others_of(characters: list[Row], cast: list[str]) -> list[str]:
    """Names and nicknames of the production's people who are NOT in the scene: free text must not name them."""
    here = {norm(c) for c in cast}
    out = []
    for c in characters:
        if norm(str(c.get("name") or "")) in here:
            continue
        out += [n for n in [str(c.get("name") or ""), *[str(a) for a in c.get("aliases") or []]] if n.strip()]
    return out


def objects_of(props: list[Row], location: Row | None, blocks: list[BlockS]) -> list[str]:
    """What the place has that a picture may show: the production's props the script or the location card names."""
    look = str((((location or {}).get("current") or {}).get("card") or {}).get("look") or "")
    text = norm(" ".join(b.text for b in blocks) + " " + look)
    return [str(p["name"]) for p in props if norm(str(p.get("name") or "")) and norm(str(p["name"])) in text]


def story_objects(props: list[Row], blocks: list[BlockS]) -> list[str]:
    """The objects the story turns on, for the craft measure: the production's props the SCRIPT names (a prop is in the
    bible because the story uses it; what only the place card has is set dressing)."""
    text = norm(" ".join(b.text for b in blocks))
    return [str(p["name"]) for p in props if norm(str(p.get("name") or "")) and norm(str(p["name"])) in text]


def _step(ident: str) -> Any:
    return parts.step(ident, "step")


def problems_of(raw: list[Row]) -> list[Problem]:
    return [Problem.model_validate(p) for p in raw]


# ── the pipeline ─────────────────────────────────────────────────────────────────────────────────


class Planner:
    """Plans one scene. `pack` is the data `jonathan_pack` is given besides the scene (production, context, link, start,
    look changes, last shot, reading); `start` is the state the scene starts from (the end state before it, when
    linked); `craft` is what the craft measures read besides the plan."""

    def __init__(self, ctx: RunContext, scene: SceneS, *, number: int, line_ids: dict[str, str], pack: Row,
                 removed: list[Removed], link: Link, start: EndStateW | None, before: EndStateW | None,
                 craft: Craft | None = None) -> None:
        self.ctx, self.scene, self.number, self.line_ids = ctx, scene, number, line_ids
        self.pack_data, self.removed, self.link, self.start, self.before = pack, removed, link, start, before
        self.craft = craft or Craft(guide_s=float(scene.envelope_s or 0))
        self.log: list[str] = []
        self.calls = {"author": 0, "revise": 0}
        self.passes: list[Row] = []
        self.mended: list[str] = []
        self.first_pass: Judged | None = None  # what code found in the author's own answer, before any revise
        self._pack: Row | None = None

    # the author's input ────────────────────────────────────────────────────────────────────────

    def pack(self) -> Row:
        if self._pack is None:
            self._pack = _step("jonathan_pack").run({
                **self.pack_data, "scene": self.scene.model_dump(mode="json"), "link": self.link.kind,
                "start": self.start.model_dump(mode="json") if self.start else None,
                "removed": [f"no {r.kind} after block b{r.after_block}" + (f" ({r.what})" if r.what else "")
                            for r in self.removed]})
        return self._pack

    def input_hash(self) -> str:
        """What Jonathan was given, as a hash: a rebuild whose hash is unchanged keeps the stored plan."""
        body = json.dumps({"pack": self.pack()["text"], "removed": [r.model_dump() for r in self.removed],
                           "scene": self.scene.model_dump(mode="json")}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def removed_pairs(self) -> list[dict[str, Any]]:
        return [r.model_dump() for r in self.removed]

    # code's steps ──────────────────────────────────────────────────────────────────────────────

    def judge(self, plan: JonathanWire, extra: list[Problem] | None = None) -> Judged:
        """Mend the plan, then check and measure it."""
        out = _step("jonathan_mend").run({"scene": self.scene.model_dump(mode="json"),
                                          "plan": plan.model_dump(mode="json"), "removed": self.removed_pairs()})
        if "malformed" in out:
            raise Failed(f"The plan could not be read: {out['malformed']}")
        mended = JonathanWire.model_validate(out["plan"])
        found = _step("jonathan_check").run({"scene": self.scene.model_dump(mode="json"),
                                             "plan": mended.model_dump(mode="json"), "removed": self.removed_pairs(),
                                             "craft": self.craft.model_dump(),
                                             "pinned": self.pack_data.get("pinned") or None})
        judged = Judged(plan=mended, problems=problems_of(found["problems"]),
                        measures=[Measure.model_validate(m) for m in found.get("measures") or []],
                        dropped=problems_of(out["dropped"]), extra=list(extra or []), mended=list(out["mended"]))
        return judged

    # the model's calls ─────────────────────────────────────────────────────────────────────────

    def ask(self, agent_id: str, inp: dict[str, Any]) -> Any:
        try:
            return agents.build(agent_id).run(inp, self.ctx)
        except Exception as exc:
            _log.warning("%s failed", agent_id, exc_info=True)
            raise Failed(f"{agent_id} could not answer ({type(exc).__name__}). Try again, or use the classic planner "
                         "for this scene.") from exc

    def author(self) -> JonathanWire:
        """ONE call. The one retry covers a call that could not be made and an answer with no shots."""
        inp = {"scene": self.scene.model_dump(mode="json"), "pack": self.pack()["text"]}
        for attempt in (1, 2):
            self.calls["author"] += 1
            try:
                out = self.ask("jonathan_author", inp)
            except Failed:
                if attempt == 2:
                    raise
                self.log.append("the author could not be reached; asking once more")
                time.sleep(BACKOFF_S)
                continue
            plan = JonathanWire.model_validate(out.model_dump(mode="json"))
            if plan.shots:
                return plan
            if attempt == 2:
                raise Failed("Jonathan wrote no shots for this scene. Use the classic planner for this scene.")
            self.log.append("the author's answer had no shots; asking once more")
        raise AssertionError("unreachable")

    def revise(self, best: Judged, note: str = "") -> JonathanWire | None:
        """One revise pass: the best plan so far and what code found in it → the whole corrected plan (None when the
        reviser could not answer or wrote no shots: the best plan stands)."""
        self.calls["revise"] += 1
        try:
            out = self.ask("jonathan_revise", {
                "scene": self.scene.model_dump(mode="json"), "pack": self.pack()["text"],
                "draft": best.plan.model_dump(mode="json"), "problems": [p.model_dump() for p in best.faults],
                "gaps": [m.model_dump() for m in best.gaps], "note": note})
        except Failed as exc:
            self.log.append(str(exc))
            return None
        plan = JonathanWire.model_validate(out.model_dump(mode="json"))
        return plan if plan.shots else None

    # the stabiliser ─────────────────────────────────────────────────────────────────────────────

    def stabilise(self, best: Judged, *, passes: int = MAX_REVISES, label: str = "revise", note: str = "",
                  extra_of: Any = None) -> Judged:
        """While a fault or a craft gap is left, send the BEST plan so far back with what code found; keep a pass only
        when its score is lower (a person's note: when it adds no fault). At most `passes` calls. `extra_of(plan)` adds
        problems from outside the plan's checks (a seam) to each pass's score."""
        for n in range(1, passes + 1):
            if best.score == (0, 0) and not note:
                break
            entry: Row = {"kind": label, "round": n, "sent": [p.sentence for p in best.faults],
                          "gaps": [f"{m.label}: {m.detail}" for m in best.gaps], "before": list(best.score),
                          "accepted": False}
            self.passes.append(entry)
            revised = self.revise(best, note)
            if revised is None:
                entry["result"] = "no answer"
                self.log.append(f"{label} pass {n}: the reviser gave no plan; the best one stands")
                break
            try:
                judged = self.judge(revised, extra_of(revised) if extra_of else None)
            except Failed as exc:
                entry["result"] = f"refused: {exc}"
                continue
            entry["after"] = list(judged.score)
            better = (len(judged.faults) <= len(best.faults)) if note else judged.score < best.score
            if better:
                entry.update({"accepted": True, "result": "kept"})
                self.mended += judged.mended
                self.log.append(f"{label} pass {n}: kept ({best.score} → {judged.score})")
                best = judged
            else:
                entry["result"] = "not better: the best plan stands"
                self.log.append(f"{label} pass {n}: not kept ({best.score} → {judged.score})")
            if note:
                break  # a person's note is one pass
        return best

    # the whole scene ───────────────────────────────────────────────────────────────────────────

    def seam_problems(self, plan: JonathanWire, link: Link) -> list[Problem]:
        if self.before is None:
            return []
        out = _step("jonathan_seams").run({"before": self.before.model_dump(mode="json"), "link": link.kind,
                                           "start": self.start.model_dump(mode="json") if self.start else None,
                                           "after": plan.model_dump(mode="json"), "number": self.number})
        return problems_of(out.get("problems") or [])

    def finish(self, best: Judged, seams: list[Problem], previous: Row, job_id: str, before_end: EndStateW | None,
               line_ids: dict[str, str] | None = None, removed: list[Removed] | None = None) -> Planned:
        plan = best.plan
        changes = _step("jonathan_seams").run({"start": self.start.model_dump(mode="json") if self.start else None,
                                               "end": plan.end_state.model_dump(mode="json"), "number": self.number})
        look = [LookChange.model_validate(c) for c in changes.get("look_changes") or []]
        first = self.first_pass
        report = {"calls": dict(self.calls), "log": list(self.log),
                  "first_pass": ([{"code": p.code, "fix": p.fix, "sentence": p.sentence} for p in first.problems]
                                 if first else []),
                  "first_score": list(first.score) if first else None,
                  "first_gaps": [m.key for m in first.gaps] if first else [],
                  "score": list(best.score),
                  "checks": {"left": len(best.problems), "dropped": [p.sentence for p in best.dropped]},
                  "totals": {"shots": len(plan.shots), "take_s": sum(s.take_s for s in plan.shots),
                             "use_s": sum(s.use_s for s in plan.shots)}}
        stored = StoredPlan(job_id=job_id, input_hash=self.input_hash(), plan=plan, link=self.link,
                            start=self.start, removed=removed if removed is not None else self.removed,
                            line_ids=line_ids or self.line_ids, mended=list(dict.fromkeys(self.mended)),
                            repairs=list(self.passes), problems=[*best.problems, *best.dropped], seams=seams,
                            measures=[m.model_dump() for m in best.measures], look_changes=look,
                            end_state=plan.end_state, previous=previous, report=report,
                            pinned=dict(self.pack_data.get("pinned") or {}))
        same = before_end is not None and before_end == plan.end_state
        return Planned(stored, changed_end=not same, log=list(self.log))

    def _first(self, plan: JonathanWire) -> Judged:
        judged = self.judge(plan)
        self.first_pass = judged
        self.mended += judged.mended
        return judged

    def plan(self, *, previous: Row, job_id: str, before_end: EndStateW | None = None) -> Planned:
        """The whole scene: the author's draft, then code's checks and, while something is left, the stabiliser."""
        best = self.stabilise(self._first(self.author()))
        link = self.link
        seams = self.seam_problems(best.plan, link)
        mendable = [p for p in seams if p.fix == "repair"]
        if mendable:  # a linked scene's join: at most ONE more pass, judged with the join counted as faults
            joined = Judged(best.plan, best.problems, best.measures, best.dropped, mendable, best.mended)
            best = self.stabilise(joined, passes=1, label="seam",
                                  extra_of=lambda p: [s for s in self.seam_problems(p, link) if s.fix == "repair"])
            seams = self.seam_problems(best.plan, link)
        return self.finish(best, seams, previous, job_id, before_end)

    def with_note(self, stored: StoredPlan, note: str, *, previous: Row, job_id: str,
                  before_end: EndStateW | None = None) -> Planned:
        """A person's note: one revise pass with the note, kept unless it adds a fault."""
        best = self.stabilise(self._first(stored.plan), passes=1, label="note", note=note)
        seams = self.seam_problems(best.plan, self.link)
        return self.finish(best, seams, previous or stored.previous, job_id, before_end)

    def remove_added(self, stored: StoredPlan, n: int, *, job_id: str) -> Planned:
        """A person takes out addition `n` (1-based, in the order of `plan.added`): no model; the same addition never
        comes back."""
        plan = stored.plan
        if not 1 <= n <= len(plan.added):
            raise Failed(f"This scene has no addition number {n}.")
        added: AddedW = plan.added[n - 1]
        shot = plan.shot(added.shot)
        if shot is None or shot.blocks or shot.lines:
            raise Failed("That addition is part of a shot that shows the script, so it cannot be taken out alone. "
                         "Plan again with a note that says what to change.")
        removed = [*stored.removed, Removed.of(plan, added)]
        self.removed = removed
        judged = self.judge(plan)  # the removed addition is now refused by the mend, with its shot
        self.mended += judged.mended
        return self.finish(judged, stored.seams, stored.previous, job_id, stored.end_state,
                           line_ids=stored.line_ids, removed=removed)
