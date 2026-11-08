"""Edit / Ask again (plan/2026-11-07 Phase 4): a turn that replaces the person's last message does not read the
replaced message or its reply, so the models never see the old words and the repeat guard does not answer "you asked
that already". The changes block names the turn's lane, so the interface offers Ask again only where nothing changed.
In-memory ports, scripted models: no network, no model."""
from __future__ import annotations

from uuid import uuid4

from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.chat_world import ChatWorld, conductor


def test_the_replaced_pair_never_reaches_the_models_and_the_lane_is_stored():
    world = ChatWorld()
    old = {"id": str(uuid4()), "kind": "user", "speaker": "Dee", "text": "OLD WORDS about the opening", "blocks": []}
    answer = {"id": str(uuid4()), "kind": "director", "speaker": "Zora", "text": "",
              "blocks": [{"kind": "text", "text": "OLD REPLY about the opening"}]}
    world.director.history = [old, answer]
    model = RoutedChatModel(routes={"zora.conduct": [conductor("chat")], "zora.reply": ["Here is why."]},
                            model_name="m", stream_phase="zora.reply")
    payload = world.payload("why does the scene open wide?").model_copy(update={"replaces": old["id"]})
    with llm.use_models(model):
        events = list(graph.run(payload, world.ctx()))
    prompts = "\n".join(str(m.content) for call in model.calls for m in call)
    assert "OLD WORDS" not in prompts and "OLD REPLY" not in prompts
    message = next(d for e, d in events if e == "message")
    changes = next(b for b in message["blocks"] if b["kind"] == "changes")
    assert changes["revision"] == 0 and changes["lane"] == "chat"


def test_without_replaces_the_earlier_pair_is_read():
    world = ChatWorld()
    world.director.history = [{"id": str(uuid4()), "kind": "user", "speaker": "Dee", "text": "OLD WORDS", "blocks": []}]
    model = RoutedChatModel(routes={"zora.conduct": [conductor("chat")], "zora.reply": ["Here is why."]},
                            model_name="m", stream_phase="zora.reply")
    with llm.use_models(model):
        list(graph.run(world.payload("why?"), world.ctx()))
    assert "OLD WORDS" in "\n".join(str(m.content) for call in model.calls for m in call)
