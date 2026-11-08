"""Stop (plan/2026-11-07 Phase 2): a person who presses Stop only stops WAITING. The browser aborts, the API's stream
closes, and the function sees it at its next write: the WSGI server closes the response, which raises `GeneratorExit`
at the frame being written. The turn is then finished without writing, so a turn's saves land together: the plan, its
revision and the reply message are all saved, or none are (never a plan edit with no message).

Each test stops the same turn at every frame in turn (before the author, during the work, during the reply), on
in-memory ports with scripted models: no network, no model.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.core import llm
from hiru_ai.core.testing import RoutedChatModel
from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.chat_world import ChatWorld, author, conductor
from tests.zora.world import ROOT

sys.path.insert(0, str(ROOT / "src" / "services" / "zora_chat"))
from zora_chat.app import handler

Row = dict[str, Any]
LENS = {"op": "set", "shot": "S03", "field": "lens", "value": "85mm"}
APPROACH = {"op": "treatment.set", "field": "approach", "value": "Cold and observed, from a distance."}


def edit_turn() -> tuple[str, dict[str, list[Any]]]:
    return "S03 on an 85", {"zora.conduct": [conductor("edit", [LENS])],
                            "zora.reply": ["Done: S03 is on an 85 now."]}


def craft_turn() -> tuple[str, dict[str, list[Any]]]:
    task = {"writes": ["treatment.approach"], "scope": [], "instruction": "make the approach colder"}
    return "make the approach colder", {"zora.conduct": [conductor("craft", tasks=[task])],
                                        "zora.author": [author([APPROACH], notes="Colder.")],
                                        "zora.reply": ["The approach is colder now."]}


def frames(world: ChatWorld, message: str, routes: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch,
           stop_after: int | None) -> list[str]:
    """The function's frames for one turn; with `stop_after`, the client goes away after that many frames."""
    monkeypatch.setattr(handler, "run_turn", lambda req: graph.run(req, world.ctx()))
    with llm.use_models(RoutedChatModel(routes=routes, model_name="m", stream_phase="zora.reply")):
        out: list[str] = []
        stream: Iterator[str] = handler.stream(world.payload(message))
        for frame in stream:
            out.append(frame)
            if stop_after is not None and len(out) >= stop_after:
                stream.close()  # what the WSGI server does when the write to a gone client fails
                break
    return out


@pytest.mark.parametrize("turn", [edit_turn, craft_turn], ids=["edit", "craft"])
def test_stopping_at_any_frame_saves_the_whole_turn(turn: Any, monkeypatch: pytest.MonkeyPatch):
    whole = frames(ChatWorld(), *turn(), monkeypatch, None)
    assert any(f.startswith("event: plan") for f in whole) and whole[-1].startswith("event: done")
    full = ChatWorld()
    frames(full, *turn(), monkeypatch, None)
    expected = (full.plan(), len(full.revisions.rows), len(full.director.message_rows))
    assert expected[1] == 2 and expected[2] == 1  # base + turn revision, one reply

    for stop in range(1, len(whole)):
        world = ChatWorld()
        seen = frames(world, *turn(), monkeypatch, stop)
        assert len(seen) == stop
        got = (world.plan(), len(world.revisions.rows), len(world.director.message_rows))
        assert got == expected, f"stopped after frame {stop} ({seen[-1].splitlines()[0]})"


def test_a_crash_while_finishing_a_stopped_turn_is_logged_and_never_raised(monkeypatch: pytest.MonkeyPatch):
    def turn(req: Any) -> Iterator[tuple[str, Row]]:
        yield "status", {"text": "Reading"}
        raise RuntimeError("secret detail")

    monkeypatch.setattr(handler, "run_turn", turn)
    world = ChatWorld()
    stream = handler.stream(world.payload("hi"))
    assert next(stream).startswith("event: status")
    stream.close()  # no exception reaches the server
