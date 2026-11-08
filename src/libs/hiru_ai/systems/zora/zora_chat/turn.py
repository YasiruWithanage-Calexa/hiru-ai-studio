"""One Zora turn (plan/2026-11-06e §3, Phase 4). The stages are the nodes of the system's graph (`graph.py`):

    READ      the stored plan, the scene as the planner reads it, the thread, the persona
    IN CODE   "undo" / "redo" (a revision, no model) · "do it" with nothing waiting · a card still open
    CONDUCT   the small model: lane, the person's explicit changes as OPERATIONS, TASKS with declared effects and scope.
              Code checks the answer (`_does_nothing`, `_invented`, confidence) and retries ONCE, told what was wrong
    KERNEL    the person's ops on stable handles (exact undo; removals whole or not at all)
    DEPS      what went stale → tasks; an edit that dirties more than half the shots is undone and OFFERED as a re-plan
    AUTHOR    ONE strong call for all of the turn's tasks (or the variants, on the options lane)
    BOARD     the author kept to its tasks, the person's locks and the script's lines
    GATE      the planner's mend and checks; only problems THIS turn introduced count; ≤ 2 repair passes, a worse pass
              dropped; a take the person set is put back and its overrun reported (never trimmed)
    DELIVER   declared effects against the diff: one re-task, then "asked for, not done"
    SAVE      the planner's write path, shots keep their ids, a revision for undo, the seam with the next scene
    LEDGER    what changed · refused · asked for and not done · nothing changed · overruns · seams
    REPLY     written from the ledger (read last), streamed; the guards take out what cannot stand

The lab's `lab/zora/turn.py` is the same pipeline on recorded answers. Without a model key the in-code answers still
work (undo, redo, a confirmation) and anything else says plainly that Zora needs its model.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import Any

from contracts.director import TurnPayload, without_replaced
from contracts.zora import effects as E
from contracts.zora import ops as O
from contracts.zora import treatment as T
from contracts.zora.doc import Person, ZoraDoc
from contracts.zora.ledger import Ledger
from contracts.zora.render import addressable, consumer
from contracts.zora.tasks import Task, merge_tasks
from contracts.zora.wire import ConductorAnswer, to_op
from hiru_ai.core import agents, llm
from hiru_ai.core import memory as production_memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import ZoraSettings, get_settings
from hiru_ai.steps.zora.zora_board import gate
from hiru_ai.steps.zora.zora_board.logic import current, settle
from hiru_ai.steps.zora.zora_deliver.logic import report, retask, undelivered
from hiru_ai.steps.zora.zora_deps.logic import plan_tasks, recut_guard
from hiru_ai.steps.zora.zora_guard import logic as guard
from hiru_ai.steps.zora.zora_kernel.logic import ZoraKernel
from hiru_ai.steps.zora.zora_kernel.logic import settle as settle_choice
from hiru_ai.steps.zora.zora_kernel.step import kernel_for
from hiru_ai.steps.zora.zora_ledger.logic import build, change_lines
from hiru_ai.systems.zora.zora_chat import scene as world_of
from hiru_ai.systems.zora.zora_chat.store import Saver

_log = logging.getLogger(__name__)
Row = dict[str, Any]
Event = tuple[str, Row]
Emit = Callable[[str, Row], None]
MIN_CONFIDENCE = 0.5
NO_MODEL = ("I can't edit the plan right now: my model is not available. Undo and redo still work; try again in a "
            "moment.")
ROLE_REFUSAL = "Your role can comment on the plan but not change it; a director, producer or writer can."
TRANSLATE = ("Translating the dialogue is staged as a card by the classic director chat: switch this panel to the "
             "classic chat and ask there, and you accept every line before anything changes.")
CARD_WAITING = "That is waiting on the options above: choose “Use this” on the one you want."
WRITING_LANES = frozenset({"edit", "craft", "options"})
CLARIFY = ("THE REQUEST WAS NOT CLEAR: nothing was changed. Ask ONE short question that tells the two readings apart; "
           "never guess.")


def _faults(problems: list[Row]) -> list[Row]:
    return [p for p in problems if p.get("fix") != "report"]


def handles_for(plan: Row, kernel_plan: Row) -> list[str]:
    """The kernel handle of each shot of a mended plan: the same shot when the mend kept the count, else the shot that
    shows the same blocks (a mend that cut a crowded shot gives its second half a new id)."""
    ks = kernel_plan.get("shots") or []
    shots = plan.get("shots") or []
    if len(ks) == len(shots):
        return [str(s["_h"]) for s in ks]
    by_blocks = {tuple(s.get("blocks") or []): str(s["_h"]) for s in ks}
    by_first = {(s.get("blocks") or [None])[0]: str(s["_h"]) for s in ks if s.get("blocks")}
    out, used = [], set()
    for s in shots:
        h = by_blocks.get(tuple(s.get("blocks") or [])) or by_first.get((s.get("blocks") or [None])[0]) or ""
        out.append(h if h and h not in used else "")
        used.add(h)
    return out


@dataclass
class State:
    """What the turn has done so far: the ledger's raw material."""

    lane: str = ""
    fact: str = ""  # one sentence the reply must carry (an undo, a refusal of the whole request)
    refused: list[str] = field(default_factory=list)
    team_refused: list[str] = field(default_factory=list)
    undelivered: list[str] = field(default_factory=list)
    staged: list[str] = field(default_factory=list)
    mended: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    overruns: list[str] = field(default_factory=list)
    seams: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)
    proposals: list[Row] = field(default_factory=list)
    offer: str = ""
    offer_note: str = ""
    attempted: bool = False
    undone: bool = False
    revision: int = 0
    saved_shots: list[Row] = field(default_factory=list)
    goal: str = ""
    met: bool | None = None
    route: str = ""
    calls: dict[str, int] = field(default_factory=dict)


class Turn:
    def __init__(self, req: TurnPayload, ctx: RunContext, emit: Emit, settings: ZoraSettings | None = None) -> None:
        self.req, self.emit = req, emit
        self.ctx = dc_replace(ctx, scene_id=req.scene_id)
        self.cfg = settings or get_settings().zora
        self.st = State()
        self.enabled = llm.models_enabled()

    # ── read ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def read(self) -> bool:
        """→ False when there is nothing to edit (an error event was sent)."""
        req = self.req
        self.emit("status", {"text": "Reading the plan"})
        world = world_of.read(self.ctx, req.production_id, req.scene_id)
        if isinstance(world, str):
            self.emit("error", {"message": world})
            return False
        self.world = world
        self.director = self.ctx.need("director")
        person = Person.model_validate(world.stored.get("person") or {})
        self.doc = ZoraDoc(plan=world.stored["plan"], scene=world.scene, person=person)
        self.kernel = kernel_for(self.doc)
        self.before = self.kernel.export(handles=True)
        self.base = gate.judge(world.scene, self.kernel.export(), mend=False)
        self.base_handles = self.kernel.handles()
        self.saver = Saver(self.ctx, world, actor_user_id=req.actor_user_id, kept=self.cfg.revisions_kept)
        # Without this turn's own message (it is the `message`) and the pairs a person replaced (Edit / Ask again).
        history = without_replaced([m for m in self.director.messages(req.thread_id, 12)
                                    if str(m.get("id")) != str(req.user_message_id)], req.replaces)
        self.history = history
        self.transcript = [f"{m.get('speaker') or m.get('kind')}: {m.get('text') or _blocks_text(m)}" for m in history]
        seats = self.director.board(req.production_id)
        self.lead = next((s["persona"] for s in seats if s.get("seat") == "lead" and s.get("persona")), None) \
            or self.director.default_persona() or {}
        return True

    # ── in code: undo, redo, a confirmation ──────────────────────────────────────────────────────────────────────

    def in_code(self) -> str:
        """→ the lane code answers without a model ("" = conduct)."""
        msg = self.req.message
        kind = guard.undo_asked(msg)
        if kind:
            return kind
        if guard.confirms(msg):
            return "confirm"
        suggested = T.task_for(msg, self.doc.plan, self.world.scene, settled=self.doc.person.settled)
        if suggested is not None:  # a suggestion is a button: no router is asked (plan §4.11)
            self.answer = ConductorAnswer.model_validate({**suggested, "confidence": 1.0})
            for effect in suggested["settles"]:
                settle_choice(self.kernel, effect)
            return "suggested"
        return ""

    def restore(self) -> None:
        st = self.st
        st.lane = st.lane or "undo"
        if not self.req.can_edit:
            st.fact = ROLE_REFUSAL
            return
        self.emit("status", {"text": "Undoing the last change" if st.lane == "undo" else "Redoing it"})
        done = self.saver.restore(st.lane)
        if not done.ok:
            st.fact = done.reason
            return
        st.revision = done.revision
        st.saved_shots = done.rows or []
        st.fact = ("Undone: the plan is back to how it was before the last change." if st.lane == "undo"
                   else "Redone: the change is back.")
        self.after = _with_handles(self.world.stored["plan"])

    def confirm(self) -> None:
        st = self.st
        st.lane = "confirm"
        st.fact = CARD_WAITING if _open_card(self.history) else guard.NOTHING_WAITING

    # ── conduct ──────────────────────────────────────────────────────────────────────────────────────────────────

    def conduct(self) -> str:
        """→ the lane. The conductor's answer is checked in code; one retry is told what was wrong."""
        if not self.enabled:
            self.st.lane, self.st.fact = "nomodel", NO_MODEL
            return "nomodel"
        self.emit("status", {"text": "Reading your message"})
        plan_text = addressable(self.doc)
        inp: Row = {"plan": plan_text, "message": self.req.message, "transcript": self.transcript}
        answer: ConductorAnswer | None = None
        problems: list[str] = []
        for attempt in (1, 2):
            try:
                self.st.calls["conductor"] = self.st.calls.get("conductor", 0) + 1
                raw = agents.build("zora_conductor").run({**inp, "problems": problems}, self.ctx)
                answer = ConductorAnswer.model_validate(raw.model_dump(mode="json"))
            except Exception:
                _log.warning("zora conductor failed (attempt %s)", attempt, exc_info=True)
                answer = None
                break
            problems = self._problems(answer)
            if not problems:
                break
        if answer is None:
            self.st.lane = "clarify"  # the default when the router fails (W-lanes): nothing is written
            return "clarify"
        if problems:  # still wrong after the retry: drop what cannot stand, keep the rest
            answer = self._drop_invented(answer)
        if answer.confidence < MIN_CONFIDENCE and answer.lane in WRITING_LANES | {"shape"}:
            answer = ConductorAnswer(lane="clarify", confidence=answer.confidence)
        self.answer = answer
        self.st.lane = answer.lane
        if answer.memory.strip():
            self._remember(answer.memory.strip())
        return answer.lane

    def _invented(self, op: Row) -> bool:
        try:
            live = current(self.kernel.export(), to_op(op))
        except Exception:
            live = ""
        return O.invented(to_op(op), self.req.message, live if isinstance(live, str) else "")

    def _problems(self, a: ConductorAnswer) -> list[str]:
        out = []
        if a.does_nothing():
            out.append(f"lane {a.lane} carries no operations and no tasks, so it would change nothing: give the "
                       "operations or tasks the message asks for, or choose the lane that changes nothing")
        for op in a.ops:
            if self._invented(op):
                out.append(f"the {op.get('op')} on {op.get('shot') or op.get('field') or 'the plan'} writes words the "
                           "person did not say: write it as a task for the author instead")
        for t in a.tasks:
            bad = [w for w in t.writes if not E.normalize_effect(w)]
            if bad:
                out.append(f"unknown effects {', '.join(bad)}: use only the names listed")
        return out

    def _drop_invented(self, a: ConductorAnswer) -> ConductorAnswer:
        kept = []
        for op in a.ops:
            if self._invented(op):
                self.st.team_refused.append(f"a {op.get('op')} that put words in your mouth was not applied")
            else:
                kept.append(op)
        return a.model_copy(update={"ops": kept})

    def _remember(self, text: str) -> None:
        if not self.req.can_edit:
            return
        item = {"id": str(uuid.uuid4()), "production_id": str(self.req.production_id),
                "scene_id": str(self.req.scene_id), "kind": "decision", "text": text[:2000],
                "source_ref": {"user_message_id": str(self.req.user_message_id), "by": "zora"},
                "created_by": str(self.req.actor_user_id)}
        try:
            from hiru_ai.rag.embeddings import embed_texts

            vectors = embed_texts([text], "zora.memory", self.ctx.sink()) if self.enabled else None
            self.director.add_memory(item, vectors[0] if vectors else None,
                                     get_settings().openai.embedding_model if vectors else "")
        except Exception:
            _log.warning("a rule to remember was not stored", exc_info=True)

    # ── lanes that write nothing ───────────────────────────────────────────────────────────────────────────────

    def cannot(self) -> None:
        a, st = self.answer, self.st
        spec = a.cannot.model_dump() if a.cannot else {}
        st.fact = guard.cannot_text(spec)
        st.goal, st.met, st.route = guard.cannot_goal(spec), False, str(spec.get("route") or "")
        if guard.repeated(self.history, st.goal):
            st.fact = f"{st.fact} {guard.AGAIN}"

    def translate(self) -> None:
        st = self.st
        st.fact = TRANSLATE
        st.goal, st.met, st.route = "translate", False, "classic chat"
        if guard.repeated(self.history, st.goal):
            st.fact = f"{st.fact} {guard.AGAIN}"

    def shape(self) -> None:
        st = self.st
        if not self.req.can_edit:
            st.fact = ROLE_REFUSAL
            return
        task = self.answer.tasks[0].instruction if self.answer.tasks else self.req.message
        st.offer = "This is a new idea for the whole scene, more than an edit."
        st.offer_note = task or self.req.message
        st.attempted = True

    # ── the writing lanes ──────────────────────────────────────────────────────────────────────────────────────

    def edit(self) -> None:
        st, k, a = self.st, self.kernel, self.answer
        if not self.req.can_edit:
            st.fact = ROLE_REFUSAL
            st.lane = "chat"
            return
        st.attempted = True
        self.emit("status", {"text": "Applying your changes"})
        ops = [to_op(o) for o in a.ops]
        if T.treatment_mode(self.doc.plan):  # no shots yet: only the treatment and the sequences (plan §4.9)
            shot_ops = [o for o in ops if O.OPS.get(str(o.get("op")), ("", None))[0] in ("shot", "staging")]
            st.refused += [f"the {o.get('op')}: the scene has no shots yet; plan shots from this treatment first"
                           for o in shot_ops]
            ops = [o for o in ops if o not in shot_ops]
        r0 = k.apply(ops, by="conductor")
        st.refused += [str(x["reason"]) for x in r0.rejected]
        st.staged += [f"{x.get('op', {}).get('op') if isinstance(x.get('op'), dict) else x}: a change to the script "
                      "is made on the script card" for x in r0.staged]
        stale = plan_tasks(k, r0.changes)
        handles = k.handles()
        asked = [Task(tuple(e for w in t.writes if (e := E.normalize_effect(w))),
                      tuple(handles[n - 1] for n in t.scope if 1 <= n <= len(handles)),
                      instruction=t.instruction, may=tuple(e for w in t.may if (e := E.normalize_effect(w))),
                      origin="conductor", user_asked=True)
                 for t in a.tasks if any(E.normalize_effect(w) for w in t.writes)]
        tasks = merge_tasks([*asked, *stale.tasks])
        if T.treatment_mode(self.doc.plan):
            tasks = [Task(tuple(e for e in t.writes if e in T.TREATMENT_EFFECTS), t.scope, instruction=t.instruction,
                          may=tuple(e for e in t.may if e in T.TREATMENT_EFFECTS), origin=t.origin,
                          user_asked=t.user_asked) for t in tasks]
            tasks = [t for t in tasks if t.writes]
        st.stale = [k.code_of(h) for h in sorted(stale.stale, key=lambda h: k.number_of(h) or 0)]
        why = recut_guard(a.lane, "", len(self.doc.shots), stale, ratio=self.cfg.reshape_dirty_ratio,
                          min_shots=self.cfg.reshape_min_shots)
        if why:
            st.offer = f"This would change most of the scene: {why}"
            k.undo(r0)
            st.offer_note = self.req.message
            st.undone = True
            return
        self.tasks = tasks
        if not tasks:
            return
        done = [f"{x.where}: {x.text}" for x in change_lines(self.before, k.export(handles=True))]
        variants = min(int(a.variants or 2), self.cfg.variants_max) if a.lane == "options" else 0
        before_author = k.export()
        answer = self._author(tasks, done, variants=variants)
        if answer is None:
            return
        if variants:
            self._proposals(answer, tasks, before_author)
            return
        self._apply(answer, tasks, before_author)
        for _ in range(self.cfg.delivery_passes):
            missing = undelivered(tasks, self.before, k.export(handles=True))
            again = retask(missing, tasks, locked=k.locked, handles=k.handles())
            if not again:
                break
            done = [f"{x.where}: {x.text}" for x in change_lines(self.before, k.export(handles=True))]
            plan_now = k.export()
            more = self._author(again, done)
            if more is None:
                break
            self._apply(more, again, plan_now)

    def _task_views(self, tasks: list[Task]) -> list[Row]:
        k = self.kernel
        out = []
        for t in tasks:
            nums = sorted(n for h in t.scope if (n := k.number_of(h)) is not None)
            out.append({"instruction": t.instruction or t.reason or "do what the change needs",
                        "allowed": list(t.allowed),
                        "on": "any shot" if not t.scope else ", ".join(O.code(n) for n in nums),
                        "must": list(t.writes)})
        return out

    def _author(self, tasks: list[Task], done: list[str], *, variants: int = 0,
                faults: list[str] | None = None) -> Row | None:
        k = self.kernel
        whole = any(not t.scope for t in tasks)
        only = None if whole else {n for t in tasks for h in t.scope if (n := k.number_of(h)) is not None}
        inp = {"plan": addressable(k.doc(), only), "transcript": self.transcript, "done": done,
               "tasks": self._task_views(tasks), "variants": variants, "faults": list(faults or []),
               "place": str((self.world.scene.get("place") or {}).get("name") or ""),
               "people": list(self.world.scene.get("cast") or [])}
        self.emit("status", {"text": "Working on the plan" if not faults else "Fixing what the checks found"})
        try:
            self.st.calls["author"] = self.st.calls.get("author", 0) + 1
            out = agents.build("zora_author").run(inp, self.ctx)
        except Exception:
            _log.warning("zora author failed", exc_info=True)
            self.st.team_refused.append("the craft work of this turn could not be done (the model did not answer)")
            return None
        data: Row = dict(out.model_dump(mode="json"))
        if data.get("notes"):
            self.st.notes.append(str(data["notes"]))
        self.st.asks += [str(q) for q in data.get("asks") or [] if str(q).strip()]
        return data

    def _apply(self, answer: Row, tasks: list[Task], plan: Row, *, by: str = "author") -> None:
        k, st = self.kernel, self.st
        kept = settle([to_op(o) for o in answer.get("ops") or [] if isinstance(o, dict)], tasks, plan,
                      handles=k.handles(), locked=k.locked, seat="the director")
        st.team_refused += kept.refused
        res = k.apply(kept.kept, by=by)
        st.team_refused += [f"the {x['op'].get('op') if isinstance(x['op'], dict) else x['op']}: {x['reason']}"
                            for x in res.rejected]

    def _proposals(self, answer: Row, tasks: list[Task], plan: Row) -> None:
        k, st = self.kernel, self.st
        for v in (answer.get("variants") or [])[:self.cfg.variants_max]:
            trial = ZoraKernel(k.doc(), validate=k.validate)
            kept = settle([to_op(o) for o in v.get("ops") or [] if isinstance(o, dict)], tasks, plan,
                          handles=trial.handles(), locked=trial.locked)
            res = trial.apply(kept.kept, by="author")
            if not res.applied:
                continue
            judged = gate.judge(self.world.scene, trial.export())
            new = _faults(gate.new_problems(self.base.problems, self.base_handles, judged.problems, trial.handles()))
            if new:  # a proposal is offered only when it passes the planner's checks (plan 2026-11-01c verified cards)
                continue
            lines = change_lines(self.before, trial.export(handles=True))
            st.proposals.append({"label": str(v.get("label") or "An option")[:120],
                                 "detail": "; ".join(f"{x.where}: {x.text}" for x in lines[:4])[:400],
                                 "change": f"{len(lines)} change{'s' if len(lines) != 1 else ''}",
                                 "ops": res.applied, "intent": f"zora:{self.saver.read_print}"})

    # ── check, mend, repair, save ──────────────────────────────────────────────────────────────────────────────

    def settle(self) -> None:
        """The gate, the repair passes, the save. Runs after every lane; it saves only a changed plan."""
        st, k = self.st, self.kernel
        if st.lane in ("undo", "redo"):
            return
        self.after = k.export(handles=True)
        if st.offer or st.proposals or not change_lines(self.before, self.after):
            return
        pinned = {tuple(k.shot(h)["blocks"]): int(k.shot(h)["take_s"]) for h in k.pinned if k.number_of(h)}
        self.emit("status", {"text": "Checking the plan"})
        judged = gate.judge(self.world.scene, k.export())
        new = _faults(gate.new_problems(self.base.problems, self.base_handles, judged.problems, k.handles()))
        for _ in range(self.cfg.max_repairs if new and self.enabled else 0):
            before_repair, snap = k.export(), k._snapshot()
            fix = Task(tuple(dict.fromkeys(e for t in getattr(self, "tasks", []) for e in t.allowed))
                       or tuple(E.WRITES), (), instruction="repair", origin="repair")
            answer = self._author([fix], [], faults=[p["sentence"] for p in new])
            if answer is None:
                break
            self._apply(answer, [fix], before_repair, by="repair")
            again = gate.judge(self.world.scene, k.export())
            worse = _faults(gate.new_problems(self.base.problems, self.base_handles, again.problems, k.handles()))
            if len(worse) < len(new):
                judged, new = again, worse
            else:
                k._restore(snap)  # a worse pass is never built on
        self.after = k.export(handles=True)
        plan, overruns = gate.protect(k.export(), judged, pinned)
        st.overruns += overruns + gate.overruns(judged.problems)
        st.mended += judged.mended
        st.problems += [p["sentence"] for p in new]
        if not self.req.can_edit:
            return
        self.emit("status", {"text": "Saving"})
        saved = self.saver.save(plan, handles=handles_for(plan, self.after), mended=judged.mended,
                                problems=judged.problems, measures=judged.measures,
                                person=k.person().model_dump(), message_id="")
        if not saved.ok:
            st.refused.append(saved.reason)
            st.undone = True
            return
        st.revision = saved.revision
        st.saved_shots = saved.rows or []
        self._seams(plan)
        self.emit("plan", {"shots": [_shot_view(r) for r in st.saved_shots],
                           "total_s": sum(int(r.get("duration_s") or 0) for r in st.saved_shots),
                           "revision": st.revision})

    def _seams(self, plan: Row) -> None:
        nxt = self.world.next
        if not nxt.plan or not nxt.link or plan.get("end_state") == (self.doc.plan.get("end_state")):
            return
        try:
            found = gate.seams(plan["end_state"], next_plan=nxt.plan, next_link=nxt.link, next_start=nxt.start,
                               next_number=nxt.number)
        except Exception:
            _log.warning("the seam with the next scene could not be checked", exc_info=True)
            return
        self.st.seams += [f"{nxt.label}: {p['sentence']}" for p in found]

    # ── the ledger and the reply ───────────────────────────────────────────────────────────────────────────────

    def ledger(self) -> Ledger:
        st = self.st
        after = getattr(self, "after", None) or self.before
        undelivered_now = []
        if hasattr(self, "tasks") and not st.proposals and not st.undone:
            undelivered_now = report(undelivered(self.tasks, self.before, after), self.tasks,
                                     locked=self.kernel.locked, handles=self.kernel.handles())
        led = build(self.before, after, refused=st.refused, team_refused=st.team_refused,
                    undelivered=undelivered_now, attempted=st.attempted, staged=st.staged, mended=st.mended,
                    problems=st.problems, overruns=list(dict.fromkeys(st.overruns)), seams=st.seams,
                    stale=st.stale if st.revision or st.saved_shots else [], offer=st.offer,
                    undone=st.undone and st.lane not in ("undo", "redo"),
                    already=self.kernel.already() if st.attempted and hasattr(self, "kernel") else [])
        if st.lane in ("undo", "redo") and st.saved_shots:
            led = build(self.before, after, attempted=True)
        return led

    def reply(self) -> None:
        st = self.st
        ledger = self.ledger()
        self.emit("ops", ledger.event())
        self.emit("gate", ledger.gate())
        if st.proposals:
            self.emit("proposals", {"options": st.proposals})
        if st.offer:
            self.emit("confirm_reshape", {"reason": st.offer, "note": st.offer_note})
        self.emit("status", {"text": "Writing the reply"})
        text = ""
        for delta in self._reply_chunks(ledger):
            text += delta
            self.emit("delta", {"text": delta})
        if self.enabled and st.lane not in ("undo", "redo", "confirm", "nomodel"):
            kept = guard.guard_reply(text, ledger, has_card=bool(st.proposals or st.offer))
            text = kept.strip() or guard.template_reply(ledger, fact=st.fact)
        self._store(text.strip(), ledger)

    def _facts(self, ledger: Ledger) -> list[str]:
        st = self.st
        turn = []
        if st.fact:
            turn.append(f"SAY THIS FIRST, as it is: {st.fact}")
        if st.lane == "clarify":
            turn.append(CLARIFY)
        turn += ledger.context()
        if st.notes:
            turn.append("THE TEAM'S NOTE ON ITS WORK (use it only where DONE THIS TURN backs it):\n"
                        + "\n".join(f"- {n}" for n in st.notes[:3]))
        settled = self.kernel.person().settled
        asks = [q for q in st.asks if not any(T.SOFT.get(e, e).split()[-1] in q.lower() for e in settled)]
        if asks:
            turn.append("THE TEAM NEEDS TO ASK (ask it, once):\n" + "\n".join(f"- {q}" for q in asks[:2]))
        if settled:
            turn.append("HANDED OVER BY THE PERSON (never ask about these again): "
                        + ", ".join(T.SOFT.get(e, e) for e in settled))
        if st.proposals:
            turn.append("PROPOSALS SHOWN as cards under your reply; the person picks one with “Use this”: "
                        + "; ".join(p["label"] for p in st.proposals)
                        + ". Introduce them in one or two sentences; do not describe each again.")
        return turn

    def _reply_chunks(self, ledger: Ledger) -> Iterator[str]:
        st = self.st
        if not self.enabled or st.lane in ("undo", "redo", "confirm", "nomodel"):
            yield guard.template_reply(ledger, fact=st.fact) if st.lane not in ("confirm", "nomodel") else st.fact
            return
        lead = self.lead
        persona = f"You are {lead.get('name', 'the lead director')}: {lead.get('style_note', '')}" if lead else ""
        touched = {int(s["n"]) for s in (getattr(self, "after", None) or self.before).get("shots") or []
                   if any(line.where == O.code(int(s["n"])) for line in ledger.changes)}
        inp = {"persona": persona, "transcript": self.transcript, "message": self.req.message,
               "plan": consumer(self.kernel.doc(), touched or None), "turn": self._facts(ledger)}
        try:
            self.st.calls["reply"] = 1
            yield from agents.build("zora_reply").stream(inp, self.ctx)
        except Exception:
            _log.warning("zora reply failed; using the plain reply", exc_info=True)
            yield guard.template_reply(ledger, fact=st.fact)

    def _store(self, text: str, ledger: Ledger) -> None:
        st, req, lead = self.st, self.req, self.lead
        text_block: Row = {"kind": "text", "text": text}
        if st.goal:
            text_block |= {"goal": st.goal, "met": st.met, "advice": False, "route": st.route}
        suggestions = T.suggestions(self.world.stored["plan"], self.world.scene,
                                    settled=self.kernel.person().settled)
        lane = "reshape" if st.offer else st.lane
        blocks: list[Row] = [text_block, {"kind": "changes", "ops": ledger.event(), "gate": ledger.gate(),
                                          "revision": st.revision, "suggestions": suggestions, "lane": lane}]
        if st.proposals:
            blocks.append({"kind": "options", "question": "", "options": st.proposals})
        if used := production_memory.used_block(self.ctx):  # the production memory the turn's agents were given
            blocks.append(used)
        message = {"id": str(uuid.uuid4()), "production_id": str(req.production_id), "thread_id": str(req.thread_id),
                   "kind": "director", "persona_id": lead.get("id"), "speaker": lead.get("name", "Director"),
                   "tone": "lead", "text": "", "blocks": blocks, "ops": [], "citations": []}
        self.director.add_message(message)
        self.emit("message", message)
        self.emit("done", {"message_id": message["id"], "lane": lane, "revision": st.revision,
                           "suggestions": suggestions})


def _with_handles(plan: Row) -> Row:
    out = {**plan, "shots": [{**s, "_h": f"h{i}"} for i, s in enumerate(plan.get("shots") or [], start=1)]}
    return out


def _shot_view(row: Row) -> Row:
    keys = ("id", "number", "title", "framing", "duration_s", "sound_mode", "camera_link", "block_start", "block_end")
    return {k: row.get(k) for k in keys}


def _blocks_text(m: Row) -> str:
    return " ".join(str(b.get("text") or "") for b in m.get("blocks") or [] if b.get("kind") == "text").strip()


def _open_card(history: list[Row]) -> bool:
    for message in reversed(history[-8:]):
        if message.get("kind") != "director":
            continue
        cards = [b for b in message.get("blocks") or [] if b.get("kind") == "options"]
        return any(b.get("chosen") is None and any(o.get("ops") for o in b.get("options") or []) for b in cards)
    return False
