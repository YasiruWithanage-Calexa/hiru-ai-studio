"""What a reply relied on (plan/2026-11-07 Phase 3): the production-memory entries the middleware gave the turn's
agents are recorded by code as they are injected and stored on the reply message as one `used` block. A turn whose
agents were given none has no block. In-memory ports, scripted models: no network, no model."""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest

from contracts.director import ChatMessage
from hiru_ai.core import llm, memory
from hiru_ai.core.context import RunContext
from hiru_ai.core.fakes import FakeDocs, FakeMemory
from hiru_ai.core.middleware.base import ModelCall
from hiru_ai.core.middleware.production_memory import ProductionMemory
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.chat_world import ChatWorld, author, conductor

Row = dict[str, Any]
DOC = str(uuid4())
APPROACH = {"op": "treatment.set", "field": "approach", "value": "Cold and observed, from a distance."}


def entries(production: str) -> list[Row]:
    return [
        {"id": str(uuid4()), "production_id": production, "document_id": DOC, "topic": "camera",
         "applies_to": "production", "says": "Handheld only in the hospital scenes.", "strength": "must",
         "status": "approved", "source": "reader"},
        {"id": str(uuid4()), "production_id": production, "document_id": None, "topic": "tone",
         "applies_to": "production", "says": "Keep it quiet; no music under dialogue.", "strength": "prefer",
         "status": "draft", "source": "person"},
        {"id": str(uuid4()), "production_id": production, "document_id": DOC, "topic": "edit",
         "applies_to": "production", "says": "A rejected direction.", "strength": "prefer",
         "status": "rejected", "source": "reader"},
    ]


def run(world: ChatWorld, message: str, routes: dict[str, list[Any]], rows: list[Row]) -> list[tuple[str, Row]]:
    base = world.ctx()
    docs = FakeDocs([{"id": DOC, "production_id": world.production, "filename": "Director's notes.pdf"}])
    ctx = replace(base, ports=replace(base.ports, memory=FakeMemory(rows), docs=docs))
    with llm.use_models(RoutedChatModel(routes=routes, model_name="m", stream_phase="zora.reply")):
        return list(graph.run(world.payload(message), ctx))


def reply(events: list[tuple[str, Row]]) -> Row:
    return next(d for e, d in events if e == "message")


def test_a_turn_whose_author_was_given_memory_stores_what_it_was_given():
    world = ChatWorld()
    rows = entries(world.production)
    task = {"writes": ["treatment.approach"], "scope": [], "instruction": "make the approach colder"}
    events = run(world, "make the approach colder", {
        "zora.conduct": [conductor("craft", tasks=[task])], "zora.author": [author([APPROACH], notes="Colder.")],
        "zora.reply": ["The approach is colder now."]}, rows)
    message = reply(events)
    used = [b for b in message["blocks"] if b["kind"] == "used"]
    assert len(used) == 1 and message["blocks"][-1] is used[0]
    assert used[0]["memory"] == [
        {"id": rows[0]["id"], "text": rows[0]["says"], "document_id": DOC, "document_title": "Director's notes.pdf"},
        {"id": rows[1]["id"], "text": rows[1]["says"], "document_id": None, "document_title": ""},
    ]  # a rejected entry is never given, so never shown
    stored = ChatMessage.model_validate({**world.director.message_rows[-1], "created_at": "2026-11-07T10:00:00Z"})
    assert stored.blocks[-1].kind == "used"


def test_a_turn_whose_agents_were_given_no_memory_has_no_block():
    world = ChatWorld()  # an edit the person spelled out: no author is asked, so no entry is given
    lens = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
    events = run(world, "S03 on an 85", {"zora.conduct": [conductor("edit", [lens])],
                                         "zora.reply": ["Done: S03 is on an 85 now."]}, entries(world.production))
    assert all(b["kind"] != "used" for b in reply(events)["blocks"])


def a_call() -> ModelCall:
    return ModelCall(component="zora_author", phase="zora.author", tier="fast", system="s", user="u",
                     memory_topics=("*",))


def test_a_call_that_failed_relied_on_nothing():
    ctx = RunContext(production_id=UUID(int=1), ports=replace(RunContext().ports, memory=FakeMemory(
        entries(str(UUID(int=1))))))
    call = a_call()

    def boom(c: ModelCall) -> Any:
        raise RuntimeError("model down")

    with pytest.raises(RuntimeError):
        ProductionMemory()(call, ctx, boom)
    assert memory.used(ctx) == [] and memory.used_block(ctx) is None
    ProductionMemory()(a_call(), ctx, lambda c: "ok")
    ProductionMemory()(a_call(), ctx, lambda c: "ok")
    assert len(memory.used(ctx)) == 2  # given twice, recorded once each
