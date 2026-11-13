"""One Sable turn (plan/2026-11-08 §4.1, Phase 5). The stages are the nodes of the system's graph (`graph.py`):

    READ    the thread (the last 12 messages whole; older ones folded into the stored summary once the thread is long),
            the scene in view, the pre-route (`sable_route`: which tier the turn starts on)
    LOOP    ONE react agent (`sable_agent`) with its tools; the `tiering` middleware may move the turn up once. Each
            tool call shows plain words (`status`); nothing names a tool, a tier or a model
    GUARD   a quoted line no tool returned is taken out (`guard.py`); a card the person may not accept is dropped; an
            edit request becomes a handoff card to the scene's chat
    SAVE    the reply, its cards, its citations and the turn's record (`meta`, never sent to a browser) as one message

Absent-safe: with no model the turn answers one plain sentence and saves it. A person who pressed Stop gets what was
written so far, saved with "Stopped" (the handler drains the turn: plan/2026-11-07 Phase 2).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from contracts.director import without_replaced
from contracts.sable import events as E
from hiru_ai.core import agents, llm, tooling
from hiru_ai.core import memory as production_memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.errors import ModelUnavailable, ToolRefused
from hiru_ai.core.settings import SableSettings, get_settings
from hiru_ai.core.tokens import tokens_of
from hiru_ai.steps.sable.sable_route import step as route_step
from hiru_ai.systems.sable.sable_chat import guard

_log = logging.getLogger(__name__)
Row = dict[str, Any]
Emit = Callable[[str, Row], None]
FAILED = "Something went wrong on my side and I could not answer. Please ask again in a moment."
NO_CARDS = "(Your role cannot accept cards, so I proposed none.)"
CHUNK_WORDS = 8  # the reply is sent as `delta` frames of about this many words


class _Watch(BaseCallbackHandler):
    """The tool calls of the loop as they happen: plain status words for the panel, and what each tool returned (the
    quote guard's sources)."""

    raise_error = False

    def __init__(self, emit: Emit) -> None:
        self.emit = emit
        self.called: list[str] = []
        self.outputs: list[str] = []

    def on_tool_start(self, serialized: dict[str, Any], input_str: str, *, inputs: dict[str, Any] | None = None,
                      **kwargs: Any) -> None:
        name = str((serialized or {}).get("name") or kwargs.get("name") or "")
        if name not in E.STATUS:
            return
        args = inputs
        if args is None:
            try:
                args = json.loads(input_str) if input_str.startswith("{") else {}
            except ValueError:
                args = {}
        self.called.append(name)
        self.emit("status", {"text": E.status_text(name, args if isinstance(args, dict) else {})})

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        content = getattr(output, "content", output)
        self.outputs.append(content if isinstance(content, str) else str(content))


@dataclass
class State:
    history: list[Row] = field(default_factory=list)
    transcript: str = ""
    summary: str = ""
    scene_label: str = ""
    scope: Row = field(default_factory=dict)
    tier: str = route_step.BASE
    rule: str = ""
    text: str = ""
    handoff: Row | None = None
    cards: list[Row] = field(default_factory=list)
    citations: list[Row] = field(default_factory=list)
    meta: E.TurnMeta = field(default_factory=E.TurnMeta)
    sources: list[str] = field(default_factory=list)


class Turn:
    def __init__(self, req: E.SableTurnPayload, ctx: RunContext, emit: Emit, *,
                 stop: threading.Event | None = None, settings: SableSettings | None = None) -> None:
        self.req, self.emit = req, emit
        self.ctx = dc_replace(ctx, scene_id=req.scene_id, tiering={}, citations=[], tool_events=[],
                              stage_scene_only=True)
        self.stop = stop or threading.Event()
        self.cfg = settings or get_settings().sable
        self.st = State()

    # ── read ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def read(self) -> None:
        req, st = self.req, self.st
        self.emit("status", {"text": "Reading your message"})
        chat = self.ctx.need("chat", "ChatStore")
        thread = chat.thread(req.thread_id) or {}
        raw = [m for m in chat.messages(req.thread_id) if str(m.get("id")) != str(req.user_message_id)]
        history = without_replaced(raw, req.replaces)
        lines = [_line(m) for m in history]
        keep = self.cfg.history_messages
        if tokens_of("\n".join(lines)) <= self.cfg.summary_after_tokens or len(history) <= keep:
            st.transcript = "\n".join(lines)
            st.summary = ""
        else:  # the last messages whole; the older ones in the thread's stored summary, brought up to date once
            st.transcript = "\n".join(lines[-keep:])
            st.summary = self._summary(chat, thread, lines[:-keep])
        st.history = history
        if req.scene_id is not None:
            try:
                _, scene = tooling.scene_in_scope(self.ctx)
                st.scene_label = tooling.scene_label(scene)
                episode = (scene.get("episode") or {}).get("number")
                st.scope = {"episode": int(episode)} if episode is not None else {}
            except (ToolRefused, Exception):  # a scene that is gone: Sable is production-wide anyway
                _log.info("sable: the scene in view could not be read", exc_info=True)
                self.ctx = dc_replace(self.ctx, scene_id=None)
        routed = route_step.run({"message": req.message, "attachments": req.attachments})
        st.tier, st.rule = str(routed["tier"]), str(routed["rule"])
        st.meta.route_rule = st.rule

    def _summary(self, chat: Any, thread: Row, older: list[str]) -> str:
        summary = str(thread.get("summary") or "")
        done = int(thread.get("summarised") or 0)
        fresh = older[done:]
        if not fresh:
            return summary
        try:
            out = agents.build("sable_summary").run({"summary": summary, "messages": "\n".join(fresh)}, self.ctx)
            if out.summary.strip() and out.summary != summary:
                chat.set_summary(self.req.thread_id, out.summary.strip(), len(older))
                return str(out.summary.strip())
        except Exception:
            _log.warning("sable: the thread summary could not be updated; sending the recent messages only",
                         exc_info=True)
        return summary

    # ── loop ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def loop(self) -> None:
        req, st = self.req, self.st
        if not llm.models_enabled():
            st.text = E.NO_MODEL
            st.meta.failed = True
            return
        watch = _Watch(self.emit)
        inp = {"message": req.message, "history": st.transcript, "summary": st.summary, "scene": st.scene_label,
               "mentioned": "\n".join(m.text for m in req.mentions if m.text), "role": req.role,
               "can_stage": req.can_stage, "memory_scope": st.scope}
        config = {"callbacks": [watch], "tags": ["sable"],
                  "metadata": {"sable_thread": str(req.thread_id), "sable_route": st.rule or "-"}}
        try:
            out = agents.build("sable_agent").run(inp, self.ctx, config=config, tier=st.tier)
            st.text = str(out.text or "").strip()
            if out.handoff_scene.strip():
                st.handoff = {"scene": out.handoff_scene.strip(), "request": out.handoff_request.strip()}
        except ModelUnavailable:
            st.text, st.meta.failed = E.NO_MODEL, True
        except Exception:
            _log.warning("sable turn failed thread=%s", req.thread_id, exc_info=True)
            st.text, st.meta.failed = FAILED, True
        st.sources = [*watch.outputs, req.message, st.transcript, st.summary]
        st.meta.tools = list(watch.called)
        st.meta.tool_errors = sum(1 for e in self.ctx.tool_events if e.error)
        record = self.ctx.tiering
        if record:
            st.meta = st.meta.model_copy(update={k: record.get(k, "") for k in
                                                 ("tier_start", "tier_end", "escalated_by", "reason")})
        else:
            st.meta = st.meta.model_copy(update={"tier_start": st.tier, "tier_end": st.tier})

    # ── guard ─────────────────────────────────────────────────────────────────────────────────────────────────────

    def guard(self) -> None:
        st, req = self.st, self.req
        if not st.meta.failed:
            st.text, removed = guard.check(st.text, st.sources)
            st.meta.guard = removed
        staging = self.ctx.ports.staging
        staged = staging.staged() if staging is not None else []
        if staged and not req.can_stage:
            st.text = f"{st.text} {NO_CARDS}".strip()
        for card in staged if req.can_stage else []:
            if card.get("scene_id") is not None and str(card["scene_id"]) != str(req.scene_id or ""):
                _log.warning("sable: a card for another scene was dropped thread=%s", req.thread_id)
                st.meta.guard.append("card for a scene that is not open")
                continue
            block = _card(card)
            if block is not None:
                st.cards.append(block)
        if st.handoff is not None:
            block = self._handoff(st.handoff)
            if block is not None:
                st.cards.append(block)
        seen: set[str] = set()
        for c in self.ctx.citations:
            key = f"{c.get('chunk_id')}|{c.get('label')}"
            if key not in seen:
                seen.add(key)
                st.citations.append({"chunk_id": str(c.get("chunk_id") or ""), "label": str(c.get("label") or "")})

    def _handoff(self, handoff: Row) -> Row | None:
        """The scene the edit is for, inside this production; one Sable cannot find is no card (the text says why)."""
        if not handoff.get("request"):
            return None
        try:
            _, scene = tooling.scene_in_scope(self.ctx, str(handoff["scene"]))
        except Exception:
            return None
        episode = scene.get("episode_id")
        return E.Handoff(scene_id=UUID(str(scene["id"])), episode_id=UUID(str(episode)) if episode else None,
                         scene=tooling.scene_label(scene),
                         request=str(handoff["request"])[:4000]).model_dump(mode="json")

    # ── save ──────────────────────────────────────────────────────────────────────────────────────────────────────

    def save(self) -> None:
        st, req = self.st, self.req
        text = st.text or FAILED
        stopped = self.stop.is_set()
        st.meta.stopped = stopped
        if not stopped:
            for chunk in _chunks(text):
                self.emit("delta", {"text": chunk})
        for card in st.cards:
            self.emit("card", {"block": card})
        if st.citations:
            self.emit("citations", {"citations": st.citations})
        blocks: list[Row] = [E.TextBlock(text=text, stopped=stopped).model_dump(mode="json"), *st.cards]
        if used := production_memory.used_block(self.ctx):
            blocks.append(used)
        message = {"id": str(uuid.uuid4()), "production_id": str(req.production_id), "thread_id": str(req.thread_id),
                   "kind": "director", "speaker": E.SPEAKER, "text": "", "blocks": blocks, "ops": [],
                   "citations": st.citations, "meta": st.meta.model_dump(mode="json")}
        try:
            self.ctx.need("chat", "ChatStore").add_message(message)
        except Exception:
            _log.exception("sable: the reply could not be saved thread=%s", req.thread_id)
            self.emit("error", {"message": E.UNAVAILABLE})
            return
        shown = {k: v for k, v in message.items() if k not in ("meta", "production_id", "ops")}
        self.emit("message", shown)
        self.emit("done", {"message_id": message["id"], "used": (used or {}).get("memory", [])})


def _line(m: Row) -> str:
    text = str(m.get("text") or "").strip() or " ".join(
        str(b.get("text") or "") for b in m.get("blocks") or [] if isinstance(b, dict) and b.get("kind") == "text")
    cards = [b for b in m.get("blocks") or [] if isinstance(b, dict) and b.get("kind") in
             ("sable_change", "sable_state", "sable_memory", "handoff")]
    shown = "".join(f" [card: {_card_line(b)}]" for b in cards)
    return f"{m.get('speaker') or m.get('kind')}: {text.strip()}{shown}"


def _card_line(b: Row) -> str:
    if b.get("kind") == "handoff":
        return f"open {b.get('scene')} with “{b.get('request')}”"
    what = (b.get("summary") if b.get("kind") in ("sable_change", "sable_state") else f"remember: {b.get('rule')}")
    return f"{what} ({b.get('status', 'open')})"


def _card(card: Row) -> Row | None:
    """A staged card as a stored block, or None when it cannot be carried out later (no operations, or not the row
    kernel's: plan/2026-11-13 phase 8). A change is pinned to the rows by their fingerprint (`made_on`), not by ids."""
    kind = card.get("kind")
    try:
        if kind == "change":
            ops = [dict(o) for o in card.get("ops") or []]
            if not ops or card.get("engine") != "rows" or not card.get("made_on"):
                return None
            return E.StagedChange(scene_id=card["scene_id"], scene=str(card.get("scene") or ""),
                                  summary=str(card.get("summary") or ""), ops=ops, engine="rows",
                                  made_on=str(card["made_on"]),
                                  changes=[str(c) for c in card.get("changes") or []],
                                  touched=[str(t) for t in card.get("touched") or []],
                                  in_doubt=[str(d) for d in card.get("in_doubt") or []],
                                  risks=[str(r) for r in card.get("risks") or []]).model_dump(mode="json")
        if kind == "state":
            return E.StagedState(scene_id=card["scene_id"], scene=str(card.get("scene") or ""),
                                 summary=str(card.get("summary") or ""),
                                 script_version=int(card.get("script_version") or 0),
                                 marks=[dict(m) for m in card.get("marks") or []],
                                 changes=[str(c) for c in card.get("changes") or []],
                                 touched=[str(t) for t in card.get("touched") or []],
                                 in_doubt=[str(d) for d in card.get("in_doubt") or []]).model_dump(mode="json")
        if kind == "memory":
            return E.StagedMemory(rule=str(card.get("rule") or ""), scope=card.get("scope") or "production",
                                  scene_id=card.get("scene_id")).model_dump(mode="json")
    except Exception:
        _log.warning("sable: a staged card could not be shown kind=%s", kind, exc_info=True)
    return None


def _chunks(text: str) -> list[str]:
    words = text.split(" ")
    return [" ".join(words[i:i + CHUNK_WORDS]) + (" " if i + CHUNK_WORDS < len(words) else "")
            for i in range(0, len(words), CHUNK_WORDS)]
