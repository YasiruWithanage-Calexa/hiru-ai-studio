"""A Zora reply stored with its cards reads back as a `ChatMessage` (the scene page 500'd on a `confirm` block)."""
from __future__ import annotations

import uuid

from contracts.director import BoardBlock, ChatMessage, ConfirmBlock
from hiru_ai.systems.zora.zora_chat.turn import _card


def _row(blocks: list[dict]) -> dict:
    return {"id": str(uuid.uuid4()), "thread_id": str(uuid.uuid4()), "kind": "director", "speaker": "Zora",
            "tone": "lead", "text": "", "blocks": blocks, "ops": [], "citations": [],
            "created_at": "2026-11-19T10:00:00+00:00"}


def test_confirm_and_board_cards_read_back() -> None:
    confirm = _card({"ops": [{"op": {"op": "remove", "shot_id": "x"}, "by": "Zora"}], "made_on": "abc",
                     "reasons": ["removes S08, a must clip"], "lines": ["S08 removed"], "revision": 2})
    board = {"kind": "board", "shots": ["S06"], "shot_ids": [str(uuid.uuid4())],
             "reason": "the shots this change touched", "state": ""}
    m = ChatMessage.model_validate(_row([{"kind": "text", "text": "Done."},
                                         {"kind": "changes", "ops": {}, "gate": {}, "revision": 2}, confirm, board]))
    assert isinstance(m.blocks[2], ConfirmBlock) and m.blocks[2].revision == 2 and m.blocks[2].fix == ""
    assert isinstance(m.blocks[3], BoardBlock) and m.blocks[3].shots == ["S06"]
    assert m.model_dump(mode="json")["blocks"][2] == confirm


def test_hands_card_keeps_what_accept_applies() -> None:
    hands = _card({"ops": [], "made_on": "abc", "reasons": ["moves the phone"], "lines": [], "fix": "hands",
                   "marks": [{"shot": 3, "hand": "left"}], "script_version": 4, "touched": ["S03"]})
    dumped = ChatMessage.model_validate(_row([hands])).model_dump(mode="json")["blocks"][0]
    assert dumped == hands
