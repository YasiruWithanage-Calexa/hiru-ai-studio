"""The `hiru-zora-chat` function's HTTP contract (plan/2026-11-06e Phase 7): a turn streams server-sent events, an
action is plain JSON, a bad body is 400, and a crash is one sentence for the person, never an exception's text."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tests.zora.rows_world import ROOT

sys.path.insert(0, str(ROOT / "src" / "services" / "zora_chat"))
from zora_chat.app import handler


class Request:
    def __init__(self, body: Any) -> None:
        self.body = body

    def get_json(self, silent: bool = False) -> Any:
        return self.body


def turn_body() -> dict[str, Any]:
    return {"production_id": str(uuid4()), "scene_id": str(uuid4()), "thread_id": str(uuid4()),
            "actor_user_id": str(uuid4()), "actor_name": "Dee", "can_edit": True, "message": "hi",
            "user_message_id": str(uuid4())}


def test_a_turn_streams_its_events(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handler, "run_turn", lambda req: iter([("status", {"text": "Reading"}), ("done", {})]))
    from flask import Flask

    with Flask(__name__).test_request_context():
        resp = handler.handle(Request(turn_body()))
        body = "".join(c.decode() if isinstance(c, bytes) else c for c in resp.response)
    assert resp.mimetype == "text/event-stream" and "event: status" in body and "event: done" in body


def test_a_crash_is_one_error_frame_with_a_sentence(monkeypatch: pytest.MonkeyPatch):
    def boom(req: Any) -> Any:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(handler, "run_turn", boom)
    out = "".join(handler.stream(handler.TurnPayload.model_validate(turn_body())))
    assert "event: error" in out and "secret detail" not in out


def test_an_action_is_plain_json_and_a_bad_body_is_400(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(handler, "run_action", lambda req: {"ok": True, "text": f"{req.kind}"})
    body = {"action": True, "kind": "undo", "production_id": str(uuid4()), "scene_id": str(uuid4()),
            "actor_user_id": str(uuid4()), "can_edit": True}
    assert handler.handle(Request(body)) == ({"ok": True, "text": "undo"}, 200)
    assert handler.handle(Request({"action": True, "kind": "nope"}))[1] == 400
    assert handler.handle(Request({"message": "no ids"}))[1] == 400


def test_the_function_folder_is_on_the_removal_list():
    assert (Path(handler.__file__).resolve().parents[2]).name == "zora_chat"
