"""Read tools for the director (PLAN.md §6.2). They only READ: every change to the plan is a
kernel operation, so a model never writes to the database.

Scope is fixed by the turn (the production and scene the API authorised), never by the model:
a tool cannot be pointed at another production whatever its arguments say.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from contracts.canon import name_key
from director_chat.engine.kernel import ScenePlanKernel

_logger = logging.getLogger(__name__)
SNIPPET = 600

DEFINITIONS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "search_production",
        "description": "Search this production's documents (bible, scripts, notes) and its memory of past "
                       "decisions. Use for facts about characters, places, story or earlier decisions.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_canon",
        "description": "The canon card of a character, location or prop by name or code (C01, L03).",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "get_shot_timing",
        "description": "This scene's timing: each shot's start and length, when each line starts, and "
                       "what overruns.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_open_questions",
        "description": "Questions from the structure build still waiting for an answer.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}}}},
]


class StoreLike(Protocol):
    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID,
               document_ids: list[str], k: int = 6) -> list[dict[str, Any]]: ...
    def ready_documents(self, production_id: UUID) -> list[dict[str, Any]]: ...
    def open_questions(self, production_id: UUID) -> list[dict[str, Any]]: ...


class Tools:
    def __init__(self, store: StoreLike, production_id: UUID, kernel: ScenePlanKernel, canon: list[dict[str, Any]],
                 embed: Callable[[str], list[float] | None]) -> None:
        self.store, self.production_id, self.kernel, self.canon, self.embed = store, production_id, kernel, canon, embed
        self.citations: list[dict[str, Any]] = []

    def call(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            handlers: dict[str, Callable[..., str]] = {
                "search_production": self.search_production, "get_canon": self.get_canon,
                "get_shot_timing": self.get_shot_timing, "list_open_questions": self.list_open_questions}
            return handlers[name](**args)
        except Exception:
            _logger.warning("tool %s failed", name, exc_info=True)
            return json.dumps({"error": "That lookup is not available right now."})

    def search_production(self, query: str) -> str:
        docs = {str(d["id"]): d["filename"] for d in self.store.ready_documents(self.production_id)}
        rows = self.store.search(query=query[:500], embedding=self.embed(query), production_id=self.production_id,
                                 document_ids=list(docs))
        out = []
        for r in rows:
            label = docs.get(str(r.get("document_id")), "production memory")
            if r.get("heading"):
                label += f" — {r['heading']}"
            self.citations.append({"chunk_id": str(r["id"]), "label": label})
            out.append(f'<passage source="{label}">\n{str(r["content"])[:SNIPPET]}\n</passage>')
        return "\n".join(out) or "Nothing found."

    def get_canon(self, name: str) -> str:
        key = name_key(name)
        for c in self.canon:
            if key == name_key(c["code"]) or key in {name_key(n) for n in [c["name"], *(c.get("aliases") or [])]}:
                current = c.get("current") or {}
                return json.dumps({"code": c["code"], "name": c["name"], "kind": c["kind"],
                                   "locked": c.get("locked"), "card": current.get("card") or {},
                                   "wardrobe_anchor": current.get("wardrobe_anchor", ""),
                                   "voice_pin": current.get("voice_pin", "")}, ensure_ascii=False)
        return json.dumps({"error": f"No canon item called {name!r}."})

    def get_shot_timing(self) -> str:
        r = self.kernel.fit()
        return json.dumps({
            "total_s": r.total_s, "envelope_s": r.envelope_s,
            "shots": [{"shot": f"S{s.number:02d}", "start_s": s.start_s, "length_s": s.duration_s,
                       "sound": s.sound_mode.value, "words": s.words, "word_target": s.word_target} for s in r.shots],
            "lines": [{"shot": f"S{ln.shot_number:02d}", "starts_s": ln.start_s, "overrun_s": ln.overrun_s}
                      for ln in r.lines],
            "issues": [i.message for i in r.issues]}, ensure_ascii=False)

    def list_open_questions(self) -> str:
        rows = self.store.open_questions(self.production_id)
        return json.dumps([{"scope": q["scope"], "question": q["body"]} for q in rows], ensure_ascii=False)
