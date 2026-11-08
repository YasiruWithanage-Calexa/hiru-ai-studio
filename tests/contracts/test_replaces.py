"""`without_replaced`: the history a turn reads leaves out the pairs a person replaced (plan/2026-11-07 Phase 4)."""
from __future__ import annotations

from uuid import uuid4

from contracts.director import ReplacesBlock, TurnRequest, without_replaced


def _user(text: str, *blocks: dict) -> dict:
    return {"id": str(uuid4()), "kind": "user", "text": text, "blocks": list(blocks)}


def _reply(text: str) -> dict:
    return {"id": str(uuid4()), "kind": "director", "text": "", "blocks": [{"kind": "text", "text": text}]}


def test_nothing_replaced_keeps_everything():
    history = [_user("a"), _reply("A"), _user("b"), _reply("B")]
    assert without_replaced(history) == history


def test_a_replaced_pair_named_by_a_later_message_is_left_out():
    a, ra = _user("a"), _reply("A")
    b = _user("a, better", ReplacesBlock(message_id=a["id"]).model_dump(mode="json"))
    rb = _reply("B")
    assert without_replaced([a, ra, b, rb]) == [b, rb]


def test_this_turns_own_replacement_leaves_out_the_last_pair_and_all_its_replies():
    a, ra, rb = _user("a"), _reply("A"), _reply("A, part two")
    first, rfirst = _user("first"), _reply("1")
    assert without_replaced([first, rfirst, a, ra, rb], a["id"]) == [first, rfirst]


def test_replaces_is_optional_on_the_request():
    assert TurnRequest(message="hi").replaces is None
