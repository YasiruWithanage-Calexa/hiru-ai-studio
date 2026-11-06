"""One scene through Shot Planner David (plan/2026-11-05e §3, §4.4, §6).

    pack      david_pack (code)         the author's input, built from the database's rows
    author    david_author              ONE call: notes, shots with their camera design, additions, staging, end state
    mend      david_mend (code)         a longer take, a cut at a block boundary, speech out of free text, the numbering
    check     david_check (code)        every fact, each failure an exact sentence and who fixes it
    repair    david_repair              only what code cannot fix: the same strong model, the exact problems, a PATCH;
                                        code applies it, checks the whole plan again and refuses a patch that creates a
                                        new failure; at most `MAX_REPAIRS` rounds, then what is left is REPORTED
    seam      david_seams (code)        a linked scene's opening against the end state of the scene before; at most one
                                        repair

A scene that passes its checks makes ONE model call. A scene is never failed for a reported problem; it fails only when
there is no usable plan (no model, or the author's answer unusable twice), and the classic planner is the way out.

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
from contracts.david.checks import repairable
from contracts.david.plan import Problem, norm
from contracts.david.scene import BlockS, PlaceS, SceneS, plain_name
from contracts.david.stored import Link, LookChange, Removed, StoredPlan
from contracts.david.wire import AddedW, DavidWire, EndStateW, PatchWire
from hiru_ai.core import agents, parts
from hiru_ai.core.context import RunContext

_log = logging.getLogger(__name__)
Row = dict[str, Any]
NO_MODEL = "Shot Planner David needs the AI model, which is not available. Use the classic planner for this scene."
BACKOFF_S = 2.0  # the wait before the one retry of an author call that could not be made
MAX_REPAIRS = 2  # plan §6: after two rounds, what is left is reported


class Failed(Exception):
    """The scene could not be planned; the message says why, in words a person reads."""


@dataclass
class Unchanged:
    """A scene whose input is the one its stored plan was made from: it is kept as it is (plan §4.4)."""

    stored: StoredPlan


@dataclass
class Planned:
    stored: StoredPlan
    changed_end: bool = True  # its end state differs from the one stored before: the scenes after it may be out of date
    log: list[str] = field(default_factory=list)


# ── the scene, as David is given it ──────────────────────────────────────────────────────────────


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


def _step(ident: str) -> Any:
    return parts.step(ident, "step")


def problems_of(raw: list[Row]) -> list[Problem]:
    return [Problem.model_validate(p) for p in raw]


# ── the pipeline ─────────────────────────────────────────────────────────────────────────────────


class Planner:
    """Plans one scene. `pack` is the data `david_pack` is given besides the scene (production, context, link, start,
    look changes, last shot, reading); `start` is the state the scene starts from (the end state before it, when
    linked)."""

    def __init__(self, ctx: RunContext, scene: SceneS, *, number: int, line_ids: dict[str, str], pack: Row,
                 removed: list[Removed], link: Link, start: EndStateW | None, before: EndStateW | None) -> None:
        self.ctx, self.scene, self.number, self.line_ids = ctx, scene, number, line_ids
        self.pack_data, self.removed, self.link, self.start, self.before = pack, removed, link, start, before
        self.log: list[str] = []
        self.calls = {"author": 0, "repair": 0}
        self.repairs: list[Row] = []
        self.mended: list[str] = []
        self.first_pass: list[Problem] = []  # what code found in the author's answer, before any repair
        self._pack: Row | None = None

    # the author's input ────────────────────────────────────────────────────────────────────────

    def pack(self) -> Row:
        if self._pack is None:
            self._pack = _step("david_pack").run({
                **self.pack_data, "scene": self.scene.model_dump(mode="json"), "link": self.link.kind,
                "start": self.start.model_dump(mode="json") if self.start else None,
                "removed": [f"no {r.kind} after block b{r.after_block}" + (f" ({r.what})" if r.what else "")
                            for r in self.removed]})
        return self._pack

    def input_hash(self) -> str:
        """What David was given, as a hash: a rebuild whose hash is unchanged keeps the stored plan."""
        body = json.dumps({"pack": self.pack()["text"], "removed": [r.model_dump() for r in self.removed],
                           "scene": self.scene.model_dump(mode="json")}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    def removed_pairs(self) -> list[dict[str, Any]]:
        return [r.model_dump() for r in self.removed]

    # code's steps ──────────────────────────────────────────────────────────────────────────────

    def mend(self, plan: DavidWire) -> tuple[DavidWire, list[Problem]]:
        out = _step("david_mend").run({"scene": self.scene.model_dump(mode="json"),
                                       "plan": plan.model_dump(mode="json"), "removed": self.removed_pairs()})
        if "malformed" in out:
            raise Failed(f"The plan could not be read: {out['malformed']}")
        self.mended += out["mended"]
        return DavidWire.model_validate(out["plan"]), problems_of(out["dropped"])

    def check(self, plan: DavidWire) -> list[Problem]:
        out = _step("david_check").run({"scene": self.scene.model_dump(mode="json"),
                                        "plan": plan.model_dump(mode="json"), "removed": self.removed_pairs()})
        return problems_of(out["problems"])

    # the model's calls ─────────────────────────────────────────────────────────────────────────

    def ask(self, agent_id: str, inp: dict[str, Any]) -> Any:
        try:
            return agents.build(agent_id).run(inp, self.ctx)
        except Exception as exc:
            _log.warning("%s failed", agent_id, exc_info=True)
            raise Failed(f"{agent_id} could not answer ({type(exc).__name__}). Try again, or use the classic planner "
                         "for this scene.") from exc

    def author(self) -> DavidWire:
        """ONE call. The one retry covers a call that could not be made and an answer with no shots."""
        inp = {"scene": self.scene.model_dump(mode="json"), "pack": self.pack()["text"]}
        for attempt in (1, 2):
            self.calls["author"] += 1
            try:
                out = self.ask("david_author", inp)
            except Failed:
                if attempt == 2:
                    raise
                self.log.append("the author could not be reached; asking once more")
                time.sleep(BACKOFF_S)
                continue
            plan = DavidWire.model_validate(out.model_dump(mode="json"))
            if plan.shots:
                return plan
            if attempt == 2:
                raise Failed("David wrote no shots for this scene. Use the classic planner for this scene.")
            self.log.append("the author's answer had no shots; asking once more")
        raise AssertionError("unreachable")

    def repair(self, plan: DavidWire, problems: list[Problem], tried: list[str], note: str = "") -> PatchWire | None:
        self.calls["repair"] += 1
        try:
            out = self.ask("david_repair", {"scene": self.scene.model_dump(mode="json"),
                                            "plan": plan.model_dump(mode="json"),
                                            "problems": [p.model_dump() for p in problems], "tried": tried,
                                            "note": note})
        except Failed as exc:
            self.log.append(str(exc))
            return None
        return PatchWire.model_validate(out.model_dump(mode="json"))

    # settle: mend, check, repair ───────────────────────────────────────────────────────────────

    def settle(self, plan: DavidWire, *, note: str = "", rounds: int = MAX_REPAIRS, label: str = "repair",
               extra: list[Problem] | None = None) -> tuple[DavidWire, list[Problem], list[Problem]]:
        """-> (the plan, what is left, additions code dropped). Mend and check; then ask the author's model to repair
        the problems only it can, up to `rounds` times. A patch that creates a new failure is refused and counts as a
        round; an empty patch ends the loop."""
        plan, dropped = self.mend(plan)
        found = self.check(plan)
        if label == "repair" and not self.first_pass:
            self.first_pass = list(found)
        tried: list[str] = []
        pending = list(extra or [])
        for n in range(1, rounds + 1):
            ask = repairable(found) + pending
            if not ask:
                break
            patch = self.repair(plan, ask, tried, note)
            entry: Row = {"kind": label, "round": n, "sent": [p.sentence for p in ask], "accepted": False}
            self.repairs.append(entry)
            if patch is None or not (patch.replaces or patch.staging or patch.end_state):
                entry["result"] = "no change"
                self.log.append(f"{label} round {n}: the model changed nothing; the problems are reported")
                break
            try:
                candidate, more = self.mend(plan.patched(patch))
            except Exception as exc:  # a patch that cannot be applied counts as a round
                entry["result"] = f"refused: {type(exc).__name__}"
                tried.append(f"round {n} was refused: it could not be applied")
                continue
            after = self.check(candidate)
            known = {p.id for p in found if p.fix == "repair"} | {p.id for p in pending}
            fresh = [p for p in repairable(after) if p.id not in known]
            if fresh:
                entry["result"] = "refused: it created " + "; ".join(p.sentence for p in fresh)
                tried.append(f"round {n} was refused because it created: " + "; ".join(p.sentence for p in fresh))
                self.log.append(f"{label} round {n}: refused, it created {len(fresh)} new problem(s)")
                continue
            entry.update({"accepted": True, "result": "applied"})
            plan, found, dropped = candidate, after, [*dropped, *more]
            tried.append(f"round {n} changed: " + "; ".join(p.sentence[:90] for p in ask))
            pending = []
            if not repairable(found):
                break
        return plan, found, dropped

    # the whole scene ───────────────────────────────────────────────────────────────────────────

    def seam_problems(self, plan: DavidWire, link: Link) -> list[Problem]:
        if self.before is None:
            return []
        out = _step("david_seams").run({"before": self.before.model_dump(mode="json"), "link": link.kind,
                                        "start": self.start.model_dump(mode="json") if self.start else None,
                                        "after": plan.model_dump(mode="json"), "number": self.number})
        return problems_of(out.get("problems") or [])

    def finish(self, plan: DavidWire, left: list[Problem], dropped: list[Problem], seams: list[Problem],
               previous: Row, job_id: str, before_end: EndStateW | None, line_ids: dict[str, str] | None = None,
               removed: list[Removed] | None = None) -> Planned:
        changes = _step("david_seams").run({"start": self.start.model_dump(mode="json") if self.start else None,
                                            "end": plan.end_state.model_dump(mode="json"), "number": self.number})
        look = [LookChange.model_validate(c) for c in changes.get("look_changes") or []]
        report = {"calls": dict(self.calls), "log": list(self.log),
                  "first_pass": [{"code": p.code, "fix": p.fix, "sentence": p.sentence} for p in self.first_pass],
                  "checks": {"left": len(left), "dropped": [p.sentence for p in dropped]}}
        stored = StoredPlan(job_id=job_id, input_hash=self.input_hash(), plan=plan, link=self.link,
                            start=self.start, removed=removed if removed is not None else self.removed,
                            line_ids=line_ids or self.line_ids, mended=list(self.mended), repairs=list(self.repairs),
                            problems=[*left, *dropped], seams=seams, look_changes=look, end_state=plan.end_state,
                            previous=previous, report=report)
        same = before_end is not None and before_end == plan.end_state
        return Planned(stored, changed_end=not same, log=list(self.log))

    def plan(self, *, previous: Row, job_id: str, before_end: EndStateW | None = None) -> Planned:
        """The whole scene: one author call, then code's checks and, only where code cannot fix, a repair."""
        plan = self.author()
        plan, left, dropped = self.settle(plan)
        link = self.link
        seams = self.seam_problems(plan, link)
        mendable = [p for p in seams if p.fix == "repair"]
        if mendable:  # a linked scene's join: at most ONE repair, on the later scene's first shots (plan §2)
            plan, left, dropped2 = self.settle(plan, rounds=1, label="seam", extra=mendable)
            dropped += dropped2
            seams = self.seam_problems(plan, link)
        return self.finish(plan, left, dropped, seams, previous, job_id, before_end)

    def with_note(self, stored: StoredPlan, note: str, *, previous: Row, job_id: str,
                  before_end: EndStateW | None = None) -> Planned:
        """A person's note: one repair with the note as the problem (plan §4.4 Edits)."""
        issue = Problem(code="shape", sentence=f"A person asks: {note.strip()}", fix="repair", key="note")
        plan, left, dropped = self.settle(stored.plan, note=note, rounds=1, label="note", extra=[issue])
        seams = self.seam_problems(plan, self.link)
        return self.finish(plan, left, dropped, seams, previous or stored.previous, job_id, before_end)

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
        out, dropped = self.mend(plan)  # the removed addition is now refused by the mend, with its shot
        found = self.check(out)
        return self.finish(out, found, dropped, stored.seams, stored.previous, job_id, stored.end_state,
                           line_ids=stored.line_ids, removed=removed)
