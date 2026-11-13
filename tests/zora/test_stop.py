"""Stop (plan/2026-11-07 Phase 2): a person who presses Stop only stops WAITING. The browser aborts, the API's stream
closes, and the function sees it at its next write: the WSGI server closes the response, which raises `GeneratorExit`
at the frame being written. The turn is then finished without writing, so a turn's saves land together: the rows, the
revision and the reply message are all saved, or none are (never a shot edit with no message).

Each test stops the same turn at every frame in turn (before the author, during the work, during the reply), on
in-memory ports with recorded answers (plan/2026-11-13): no network, no model.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from typing import Any

import pytest

from hiru_ai.systems.zora.zora_chat import graph
from tests.zora.rows_world import ROOT, Recorded, RowsWorld

sys.path.insert(0, str(ROOT / "src" / "services" / "zora_chat"))
from zora_chat.app import handler

Row = dict[str, Any]


def edit_turn() -> tuple[str, Recorded]:
    return "Make S01 a wide, 6 seconds.", Recorded(reply="I opened S01 up.")


def craft_turn() -> tuple[str, Recorded]:
    conductor = {"lane": "craft", "confidence": 0.9, "ops": [], "variants": 0, "cannot": None, "memory": "",
                 "tasks": [{"writes": ["camera"], "shots": [10], "instruction": "tenser"}]}
    author = {"notes": "Closer.", "asks": [], "variants": [],
              "ops": [{"op": "set", "shot": "S10", "field": "size", "value": "CU"}]}
    return "Make S10 tenser.", Recorded(conductor=conductor, authors=[author], reply="Closer on Nimal now.")


def frames(world: RowsWorld, message: str, models: Recorded, monkeypatch: pytest.MonkeyPatch,
           stop_after: int | None) -> list[str]:
    """The function's frames for one turn; with `stop_after`, the client goes away after that many frames."""
    monkeypatch.setattr(handler, "run_turn", lambda req: graph.run(req, world.ctx(), ask=models.ask, say=models.say))
    out: list[str] = []
    stream: Iterator[str] = handler.stream(world.payload(message))
    for frame in stream:
        out.append(frame)
        if stop_after is not None and len(out) >= stop_after:
            stream.close()  # what the WSGI server does when the write to a gone client fails
            break
    return out


def state(world: RowsWorld) -> tuple[Any, ...]:
    shots = [(r["id"], r["framing"], r["duration_s"]) for r in world.scenes.shots(world.scene_id)]
    zora = [m for m in world.director.history if m.get("kind") == "director"]
    return shots, len(world.revisions.rows), len(zora)


@pytest.mark.parametrize("turn", [edit_turn, craft_turn], ids=["edit", "craft"])
def test_stopping_at_any_frame_saves_the_whole_turn(turn: Any, monkeypatch: pytest.MonkeyPatch):
    whole = frames(RowsWorld(), *turn(), monkeypatch, None)
    assert any(f.startswith("event: plan") for f in whole) and whole[-1].startswith("event: done")
    full = RowsWorld()
    frames(full, *turn(), monkeypatch, None)
    expected = state(full)
    assert expected[1] == 2 and expected[2] == 1  # base + turn revision, one reply

    for stop in range(1, len(whole)):
        world = RowsWorld()
        seen = frames(world, *turn(), monkeypatch, stop)
        assert len(seen) == stop
        assert state(world) == expected, f"stopped after frame {stop} ({seen[-1].splitlines()[0]})"


def test_a_crash_while_finishing_a_stopped_turn_is_logged_and_never_raised(monkeypatch: pytest.MonkeyPatch):
    def turn(req: Any) -> Iterator[tuple[str, Row]]:
        yield "status", {"text": "Reading"}
        raise RuntimeError("secret detail")

    monkeypatch.setattr(handler, "run_turn", turn)
    world = RowsWorld()
    stream = handler.stream(world.payload("hi"))
    assert next(stream).startswith("event: status")
    stream.close()  # no exception reaches the server
