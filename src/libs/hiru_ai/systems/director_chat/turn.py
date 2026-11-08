"""One director-chat turn: conduct -> apply -> tasks -> specialists -> board -> verify -> reply. Ported from
`director_chat/engine/turn.py`; the stages are the nodes of the system's graph (`graph.py`) and the routing between
them is the graph's, so a reader sees the turn's shape and not an 1,100-line function.

  1. CONDUCT   the conductor (model, or rules without a key) picks the lane and transcribes the person's explicit
               edits as operations.
  2. APPLY     the kernel applies them (the person's own words pass their own locks). An edit that would
               restructure most of the scene is undone and offered as a re-split.
  3. TASKS     from the conductor (craft lane) and from the dependency rules (a split or an inserted shot needs
               framing; a change that made a line overrun needs the editor).
  4. ROUND 1   specialists in parallel on scoped slices (the `director_board` panel); the board settles collisions
               by ownership; the kernel applies what survives under the agents' locks.
  5. VERIFY    the kernel re-times the scene. An overrun THIS turn introduced gets one bounded second round with the
               editor; whatever remains is reported, never trimmed.
  6. PERSIST   shots (ids kept), lines re-bound, audit entries (agent + person), memory.
  7. REPLY     streamed, written from the diff and the notes; advisors add their view.

The `options` lane skips 2-6: the lead offers choices, each tried on a copy of the scene, and the person applies one
later (`choice.py`). A request this chat cannot meet is lane `cannot`: nothing is applied and the reply says why and
where the person can do it. The script stays in the language it was written in; only when the person asks for the
dialogue in another language does the translator run (lane `translate`), and its lines are staged as a card like any
dialogue change. "i confirm", "do it" and "apply it" are answered in code: they apply the thread's pending action or
say that nothing is waiting. Dialogue changes only in a person's own words, only with `can_edit_script`, and never
unseen: the turn STAGES it as an options card (Apply / Keep). Nothing here can change another scene or production.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from dataclasses import replace
from typing import Any

from contracts.director import TurnPayload, without_replaced
from contracts.production import ProductionSettings
from hiru_ai.core import agents
from hiru_ai.core import memory as production_memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.settings import get_settings
from hiru_ai.rag.embeddings import embed_query, embed_texts
from hiru_ai.steps.scene_kernel import conductor, loop, options, pending, proposals, tools, translate
from hiru_ai.steps.scene_kernel.logic import ScenePlanKernel
from hiru_ai.steps.scene_kernel.turn_logic import (
    NOTHING_WAITING,
    SCRIPT_CONFLICT,
    SHORT_FOLLOW_WORDS,
    WAITING_ON_CARD,
    ScriptConflict,
    TurnState,
    blocks_text,
    cannot_text,
    describe_op,
    fit_text,
    kernel_for,
    line_blocks,
    norm,
    persist,
    receipts,
    scene_now,
    split_points,
    state_fact,
    template_reply,
)
from hiru_ai.systems.director_chat import edits, staged
from hiru_ai.systems.director_chat.models import Models
from hiru_ai.systems.director_chat.view import DirectorView

_logger = logging.getLogger(__name__)
Event = tuple[str, dict[str, Any]]
MAX_TOOL_ROUNDS = 3
Emit = Callable[[str, dict[str, Any]], None]


def scene_brief(kernel: ScenePlanKernel) -> str:
    """What replaces the whole shot list in a tool loop's prompt: how big the scene is, and where to read the rest."""
    n = len(kernel.shots)
    span = f"-S{n:02d}" if n > 1 else ""
    return (f"{n} shot{'s' if n != 1 else ''}, numbered S01{span}. The script, the spoken lines and the shot list are "
            "read with scene_read; one shot with shot_read; the timing with timing_check.")


def cited(*groups: list[dict[str, str]], limit: int = 8) -> list[dict[str, str]]:
    """The reply's citations: those of the director's own search, then those of the search tools, each passage once."""
    seen: dict[str, dict[str, str]] = {}
    for group in groups:
        for c in group:
            seen.setdefault(c["chunk_id"], c)
    return list(seen.values())[:limit]


class Turn:
    """The state of one turn, and what each stage does with it. `emit(event, data)` sends an event to the person."""

    def __init__(self, req: TurnPayload, ctx: RunContext, emit: Emit) -> None:
        # The scene is in scope for every tool a model of this turn may call (plan/2026-11-04 §4.4): it comes from the
        # trusted payload, never from what a model says. `said` is filled in once the thread has been read.
        ctx = replace(ctx, scene_id=req.scene_id)
        self.req, self.ctx, self.emit = req, ctx, emit
        self.store = DirectorView(ctx)
        self.models = Models(ctx)
        self.st = TurnState()
        self.route = "end"

    # ── 0. read ────────────────────────────────────────────────────────────────────────────────────────────────────

    def read(self) -> bool:
        """-> False when the scene is gone (an error event was sent)."""
        req, store = self.req, self.store
        pid, sid = req.production_id, req.scene_id
        self.emit("status", {"text": "Reading the scene"})
        production = store.production(pid)
        scene = store.scene(pid, sid)
        if production is None or scene is None:
            self.emit("error", {"message": "This scene is no longer available."})
            return False
        self.production, self.scene = production, scene
        self.settings = ProductionSettings.model_validate(production.get("settings") or {})
        self.lines = store.lines(sid)
        self.shot_rows = store.shots(sid)
        self.canon = store.canon(pid)
        self.kernel = kernel_for(scene, self.lines, self.shot_rows, self.settings.fixed_shot_seconds, self.canon)
        seats = store.board(pid)
        self.lead = next((s["persona"] for s in seats if s["seat"] == "lead" and s.get("persona")), None) \
            or store.default_persona() or {}
        self.advisors = [s["persona"] for s in seats if s["seat"] == "advisor" and s.get("persona")]
        # The API stored this turn's message before calling; it is the `message`, not history. A pair a person
        # replaced (Edit / Ask again) is not history either.
        self.history = without_replaced([m for m in store.messages(req.thread_id)
                                         if str(m.get("id")) != str(req.user_message_id)], req.replaces)
        self.memory = [m["text"] for m in store.memory(pid)]
        # What the person wrote, here and earlier: the only words a dialogue change may use.
        self.earlier = [str(m.get("text") or "") for m in self.history if m.get("kind") == "user" and m.get("text")]
        self.written = "\n".join([req.message, *self.earlier])
        self.ctx = replace(self.ctx, said=self.written)  # `dialogue_check` holds a line to these words
        self.models.ctx = self.ctx
        self.said = "\n".join(f"- {t}" for t in self.earlier[-6:])
        self.before = self.kernel.fit()
        self.waiting = pending.current(store, req.thread_id)  # an edit a confirmation would apply
        self.history_text = "\n".join(
            f"{m['speaker'] or m['kind']}: {m.get('text') or blocks_text(m)}" for m in self.history[-8:])
        return True

    # ── 1. conduct ─────────────────────────────────────────────────────────────────────────────────────────────────

    def conduct(self) -> str:
        """Read the message and decide which branch of the turn runs. -> the route."""
        req, st, kernel, models = self.req, self.st, self.kernel, self.models

        def conducting(again: bool = False) -> conductor.Plan | None:
            try:
                return conductor.by_model(models.conductor, plan_text=kernel.describe(), message=req.message,
                                          history=self.history_text, memory=self.memory, said=self.said, again=again,
                                          earlier=self.earlier[-6:])
            except Exception:
                _logger.warning("conductor failed; reading the message by rules", exc_info=True)
                return None

        # A model answer that would change nothing is asked once more (Nova W6) before the turn settles for it.
        plan = conducting() if models.enabled and not conductor.is_exact_command(req.message) else None
        if plan is not None and plan.lane in ("edit", "craft") and not (plan.ops or plan.tasks):
            plan = conducting(again=True) or plan
        if plan is None:
            plan = conductor.by_rules(req.message, split_points=split_points(kernel), line_blocks=line_blocks(kernel),
                                      translator=models.enabled, earlier=self.earlier[-6:])
        self.plan = plan
        st.lane, st.memory = plan.lane, plan.memory
        translating = plan.lane == "translate"
        self.translating = translating
        self.spec = translate.Spec.of(plan.translate)
        wants_change = plan.lane in ("edit", "craft", "reshape") and (plan.ops or plan.tasks or plan.lane == "reshape")
        self.wants_change = bool(wants_change)
        # "i confirm", "do it": answered in code. What they confirm is the thread's pending action, else the
        # director's last advice, else nothing: then the person is told so, with where their last request CAN be done.
        # A model never decides this.
        agreeing = proposals.agrees(req.message) and not wants_change
        # "put it in Sinhala, i confirm it" with that very card waiting applies it; any other translation is a new card
        waiting = self.waiting
        self.confirm_waiting = agreeing and waiting is not None and (
            not translating or str(waiting.get("intent") or "") == loop.translate_goal(self.spec))
        advice = proposals.latest_advice(self.history) if agreeing and waiting is None and not translating else None
        if proposals.confirms(req.message) and not wants_change and waiting is None and not translating and not (
                advice and advice.kind == "text" and models.enabled):
            st.cannot = plan.cannot if plan.lane == "cannot" else None
            st.route = st.cannot["route"] if st.cannot else proposals.last_route(self.history)
            if advice and advice.kind == "card":
                st.blocked = WAITING_ON_CARD
            else:
                st.fixed = NOTHING_WAITING + (f" {st.route}" if st.route else "")
            st.lane = "chat"
        elif plan.lane == "cannot":
            st.cannot, st.route = plan.cannot, (plan.cannot or {}).get("route", "")
        # What was asked for, kept on the reply; asking for the same unmet thing again is answered, not retried.
        if translating:
            st.goal = loop.translate_goal(self.spec)
        elif st.cannot:
            st.goal = loop.cannot_goal(st.cannot)
        if st.goal and not self.confirm_waiting and not st.fixed and not st.blocked \
                and loop.repeated(self.history, st.goal):
            st.fixed = loop.reply(self.history, cannot_text=cannot_text(st.cannot) if st.cannot else "",
                                  waiting=waiting is not None)
            st.lane = "chat"
        # "Do that", "yes": the person answers the director's last suggestion. It is found in the stored thread, in
        # code; a model that wrote nothing for a short message like it gets the same reading.
        self.follow = None
        short = plan.lane in ("edit", "craft") and len(req.message.split()) <= SHORT_FOLLOW_WORDS
        said_nothing_to_act_on = not (wants_change or st.fixed or st.blocked or plan.lane in ("cannot", "translate"))
        if models.enabled and said_nothing_to_act_on and waiting is None \
                and (proposals.refers_back(req.message) or short):
            self.follow = advice or proposals.latest_advice(self.history)
        self.acts = bool(wants_change or self.follow or self.confirm_waiting)
        self.shapes = bool(plan.tasks) or plan.lane in ("craft", "reshape") or self.follow is not None
        return self._route()

    def _route(self) -> str:
        req, st, plan = self.req, self.st, self.plan
        if self.confirm_waiting and self.waiting is not None:
            return "confirm"
        if st.fixed or st.cannot:
            return "none"  # said in code: nothing to apply, nothing to ask a model to decide
        if self.translating:
            return "translate"
        if self.acts and not (req.can_edit or (req.can_edit_script and not self.shapes)):
            st.blocked = ("Your role on this production can comment but not change the shot list; a director or "
                          "producer can apply this.")
            return "none"
        if self.acts and self.scene["status"] == "approved":
            st.blocked = "This scene is approved and locked. Unlock it before changing it."
            return "none"
        if self.acts and not self.kernel.shots:
            st.blocked = "This scene has no shots yet. Use Re-split to plan them from the script."
            return "none"
        if plan.lane == "reshape":
            return "reshape"
        if self.wants_change:
            return "edit"
        if self.follow is not None:
            return "follow"
        if plan.lane == "options" and self.models.enabled:
            return "options"
        return "none"

    # ── 2..5. the branches ─────────────────────────────────────────────────────────────────────────────────────────

    def confirm(self) -> None:
        assert self.waiting is not None
        self.emit("status", {"text": "Applying the change that was waiting"})
        for event, data in edits._confirm_pending(self.waiting, self.st, self.req, self.store, self.kernel,
                                                  self.settings):
            self.emit(event, data)

    def translate(self) -> None:
        self.emit("status", {"text": "Translating the dialogue"})
        edits._translate_turn(self.kernel, self.spec, self.st, self.models, self.lead, self.req, self.scene,
                              self.production, self.memory)

    def reshape(self) -> None:
        self.st.reshape = True

    def edit(self) -> None:
        self.emit("status", {"text": "Applying your changes"})
        self.st = edits._edit(self.kernel, self.plan, self.st, self.models, self.lead, self.before, self.req,
                              self.written)

    def follow_up(self) -> None:
        assert self.follow is not None
        self.emit("status", {"text": "Turning that into changes"})
        edits._follow_up(self.follow, self.st, self.kernel, self.models, self.lead, self.req, self.history_text,
                         self.memory)

    def weigh_options(self) -> None:
        st = self.st
        self.emit("status", {"text": "Weighing the options"})
        st.options = options.propose(self.models.options, kernel=self.kernel, message=self.req.message,
                                     history=self.history_text, lead_charter=self.lead.get("charter", ""),
                                     memory=self.memory)
        if st.options is None:
            st.lane = "chat"  # nothing worth offering: answer it as a question

    # ── 6. persist, remember, advise ───────────────────────────────────────────────────────────────────────────────

    def settle(self) -> None:
        req, st, kernel = self.req, self.st, self.kernel
        pid = req.production_id
        after = kernel.fit()
        if st.applied and not st.saved:
            new_issues = [i.message for i in after.issues if i.message not in {b.message for b in self.before.issues}]
            new_issues += [n for n in kernel.notes if n not in new_issues]  # a merge that crowds a shot
            st.continuity += new_issues
            try:
                shots_out, _ = persist(self.store, kernel, self.scene, self.shot_rows, self.lines, production_id=pid,
                                       actor_user_id=req.actor_user_id, action="scene.director_edit",
                                       applied=st.applied)
            except ScriptConflict:
                st.applied, st.flags, st.continuity, st.blocked = [], [], [], SCRIPT_CONFLICT
            else:
                self.emit("plan", {"shots": shots_out, "total_s": after.total_s,
                                   "issues": [i.message for i in after.issues]})

    def remember(self) -> None:
        req, st = self.req, self.st
        # A rule the production already holds is not stored again (the model may echo one from the history).
        known = {norm(m) for m in self.memory}
        st.memory = [t for t in dict.fromkeys(st.memory) if norm(t) not in known]
        if not (req.can_edit and st.memory):
            return
        for text in st.memory:
            item = {"id": str(uuid.uuid4()), "production_id": str(req.production_id), "scene_id": str(req.scene_id),
                    "kind": "decision", "text": text, "source_ref": {"user_message_id": str(req.user_message_id)},
                    "created_by": str(req.actor_user_id)}
            embedding = None
            if self.models.enabled:
                try:
                    embedding = embed_texts([text], "director.memory", self.ctx.sink())[0]
                except Exception:
                    _logger.warning("memory embedding failed; kept for keyword search", exc_info=True)
            self.store.add_memory(item, embedding, get_settings().openai.embedding_model if embedding else "")

    def advise(self) -> None:
        st = self.st
        if not (self.models.enabled and self.advisors and st.applied and not st.saved):
            return
        summary = "; ".join(describe_op(o) for o in st.applied)
        reviews = [{"name": adv["name"], "charter": adv.get("charter", ""), "summary": summary}
                   for adv in self.advisors[:2]]
        for view in self.models.advice(reviews, scene_text=self.kernel.describe()):
            if view:
                # The lead's side is what the plan now holds; the advisor's is a view, not an edit.
                st.disagreements.append({"title": f"{view['who']} sees it differently",
                                         "positions": [{"who": self.lead.get("name", "Lead"), "text": summary,
                                                        "applied": True}, view]})

    # ── 7. reply ───────────────────────────────────────────────────────────────────────────────────────────────────

    def embed(self, query: str) -> list[float] | None:
        if not self.models.enabled:
            return None
        return embed_query(query, "director.search", self.ctx.sink())

    def reply_chunks(self, read_tools: tools.Tools) -> Iterator[str]:
        req, st, kernel, lead = self.req, self.st, self.kernel, self.lead
        fit = fit_text(kernel)
        # A change waiting on the person is stated exactly, not written by a model that may read an old reply in the
        # chat ("the line is locked") and repeat it.
        if not self.models.enabled or st.blocked or st.fixed or (st.staged and not st.applied):
            yield template_reply(st, fit)
            return
        facts = [fit, "Scene now: " + scene_now(kernel).replace("\n", " ")]
        if not st.applied:
            facts.append("Applied this turn: nothing (this message changed neither the shot list nor the script). "
                         "Changes made earlier, including by a card the person chose, are in the recent chat.")
        if st.applied:
            facts.append("Applied: " + "; ".join(f"{describe_op(o)} (by {o['by']})" for o in st.applied))
        if st.rejected:
            facts.append("Refused: " + "; ".join(r["reason"] for r in st.rejected))
        if st.staged:
            facts.append("Waiting for the person to accept (nothing is changed yet): " + st.staged)
        if st.reshape:
            facts.append("Not applied: it would change most of the scene; suggest Re-split.")
        if st.notes:
            facts.append("Specialist notes: " + " | ".join(st.notes))
        if st.memory:
            facts.append("Stored as a production rule: " + " ".join(st.memory))
        if st.options:
            facts.append("Options are shown as cards under your reply; the person applies one with a click: "
                         + "; ".join(o["label"] for o in st.options["options"])
                         + ". Introduce them in one or two sentences. Do not list, number or describe them again.")
        if st.cannot:  # the last line of the ledger, so it is the last thing the model reads before it writes
            facts.append(f"Not possible here: {st.cannot['reason']} The person can: {st.cannot['route']}")
        persona = f"You are {lead.get('name', 'the lead director')}: {lead.get('style_note', '')}" if lead else ""
        inp = {"persona": persona, "history": self.history_text, "shot_list": kernel.describe(),
               "message": req.message, "turn": facts}
        try:
            thread = None
            if st.lane == "chat":
                # Questions may need the read tools; the final answer comes back whole.
                answerer = agents.build("chat_answerer")
                if answerer.uses_tools:  # a tool loop: a one-line summary of the scene, the tools read the rest
                    yield answerer.run({**inp, "shot_list": scene_brief(kernel)}, self.ctx).text
                    return
                answer, thread = answerer.tool_rounds(
                    inp, self.ctx, tools=tools.DEFINITIONS, call_tool=read_tools.call, rounds=MAX_TOOL_ROUNDS)
                if answer is not None:
                    yield answer
                    return
            # `medium`, not `low`: the smallest tier described changes it had not been given (replay, 2026-10-24).
            yield from agents.build("reply_writer").stream(inp, self.ctx, messages=thread)
        except Exception:
            _logger.warning("reply model failed; using the plain reply", exc_info=True)
            yield template_reply(st, fit)

    def reply(self) -> None:
        req, st, kernel, lead = self.req, self.st, self.kernel, self.lead
        pid, sid = req.production_id, req.scene_id
        self.emit("status", {"text": "Writing the reply"})
        read_tools = tools.Tools(self.store, pid, kernel, self.canon, self.embed)
        reply = ""
        for delta in self.reply_chunks(read_tools):
            reply += delta
            self.emit("delta", {"text": delta})
        # What a model's `stage` tools left (a change, a rule to remember) is shown as the card a person accepts.
        if (staging := self.ctx.ports.staging) is not None:
            st.options = staged.merge(st.options, staging.staged(), self.kernel, str(sid))
        if self.models.enabled and not st.blocked and not st.fixed:
            # A reply may point at a card only when this message carries one, offer to do something later only when a
            # card or a pending action waits, and say a change was made only when a receipt or the scene shows it. The
            # stored message (which the browser shows in place of the streamed text) is the corrected one.
            kept = proposals.guard_reply(reply, has_card=bool(st.options or st.disagreements),
                                         pending=self.waiting is not None,
                                         receipts=receipts(st, kernel, self.history), state_fact=state_fact(kernel))
            if kept != reply:
                reply = kept.strip() or template_reply(st, fit_text(kernel))
        text_block: dict[str, Any] = {"kind": "text", "text": reply.strip()}
        if st.cannot or st.fixed or st.blocked:  # nothing in it for a later "do it" to follow up
            text_block |= {"advice": False, "route": st.route}
        if st.goal:
            text_block |= {"goal": st.goal, "met": st.met}
        blocks: list[dict[str, Any]] = [text_block]
        if st.options:
            blocks.append(st.options)
        if st.applied:
            blocks.append({"kind": "edit-note", "count": len(st.applied),
                           "text": "; ".join(describe_op(o) for o in st.applied)})
        for d in st.disagreements:
            blocks.append({"kind": "disagreement", "title": d["title"], "positions": d["positions"]})
        notes = [*st.flags, *({"text": c, "shots": []} for c in st.continuity)]
        for note in notes[:4]:
            blocks.append({"kind": "continuity", "text": note["text"], "shots": note["shots"]})
        if used := production_memory.used_block(self.ctx):  # the production memory the turn's agents were given
            blocks.append(used)
        message = {"id": str(uuid.uuid4()), "production_id": str(pid), "thread_id": str(req.thread_id),
                   "kind": "director", "persona_id": lead.get("id"), "speaker": lead.get("name", "Director"),
                   "tone": "lead", "text": "", "blocks": blocks, "ops": st.applied,
                   "citations": cited(read_tools.citations, self.ctx.citations)}
        self.store.add_message(message)
        if st.options:  # a card that offers one edit leaves a pending action behind
            if (row := pending.for_card(message, production_id=pid, thread_id=req.thread_id, scene_id=sid,
                                        user_id=req.actor_user_id)):
                pending.open_new(self.store, row)
            else:
                pending.close(self.store, req.thread_id, pending.SUPERSEDED)
        self.emit("message", message)
        self.emit("done", {"message_id": message["id"], "lane": "reshape" if st.reshape else st.lane})

