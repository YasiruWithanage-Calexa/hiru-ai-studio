"""Pending actions: what "i confirm", "do it" and "apply it" are answers to (plan/2026-11-01c, Phase 2).

A card that offers ONE edit (Apply this change / Keep it as it is) leaves a pending action behind: the
edit, the card and option it belongs to, and a 24 h expiry. At most one is open per thread. A later
confirmation applies it in code, through the same `choice.apply_choice` the button uses, so no model
decides whether something was confirmed. Choosing on the card, a newer card, or the clock closes it.

The row is a convenience, never the authority: it is only honoured while the card it came from still
waits for a choice (`current` re-reads the card), and a store without the table (a database not yet on
this schema) simply has none, so every confirmation says there is nothing waiting.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

_logger = logging.getLogger(__name__)
HOURS = 24
CLOSED, APPLIED, EXPIRED, SUPERSEDED = "closed", "applied", "expired", "superseded"


def for_card(message: dict[str, Any], *, production_id: Any, thread_id: Any, scene_id: Any, user_id: Any,
             now: datetime | None = None) -> dict[str, Any] | None:
    """The pending action a stored director message leaves: its first options card with exactly one
    option that carries an edit (the "apply" option). A card of several edits, or none, leaves nothing."""
    for index, block in enumerate(message.get("blocks") or []):
        if block.get("kind") != "options" or block.get("chosen") is not None:
            continue
        with_edit = [i for i, o in enumerate(block.get("options") or []) if o.get("ops")]
        if len(with_edit) != 1:
            continue
        option = block["options"][with_edit[0]]
        return {"id": str(uuid.uuid4()), "production_id": str(production_id), "thread_id": str(thread_id),
                "scene_id": str(scene_id), "message_id": str(message["id"]), "block": index, "option": with_edit[0],
                "intent": str(option.get("intent") or ""), "label": str(option.get("label") or "")[:200],
                "ops": option["ops"], "status": "open", "created_by": str(user_id),
                "expires_at": ((now or datetime.now(UTC)) + timedelta(hours=HOURS)).isoformat()}
    return None


def open_for(store: Any, thread_id: Any) -> dict[str, Any] | None:
    try:
        return store.open_pending(thread_id)
    except Exception:
        _logger.warning("pending action lookup failed; treating it as none", exc_info=True)
        return None


def current(store: Any, thread_id: Any, now: datetime | None = None) -> dict[str, Any] | None:
    """The thread's pending action if it can still be confirmed: open, not expired, and its card still
    waiting for a choice. One that cannot is closed on the way."""
    row = open_for(store, thread_id)
    if row is None:
        return None
    moment = now or datetime.now(UTC)
    try:
        expires = datetime.fromisoformat(str(row["expires_at"]))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= moment:
            close(store, thread_id, EXPIRED)
            return None
        message = store.message(row["message_id"])
        blocks = (message or {}).get("blocks") or []
        card = blocks[int(row["block"])] if int(row["block"]) < len(blocks) else None
        if not card or card.get("kind") != "options" or card.get("chosen") is not None:
            close(store, thread_id, CLOSED)
            return None
    except Exception:
        _logger.warning("pending action unreadable; treating it as none", exc_info=True)
        return None
    return row


def close(store: Any, thread_id: Any, status: str) -> None:
    try:
        store.close_pending(thread_id, status)
    except Exception:
        _logger.warning("could not close the pending action", exc_info=True)


def open_new(store: Any, row: dict[str, Any]) -> None:
    """Store `row` as the thread's open pending action; any earlier one is superseded first."""
    try:
        store.close_pending(row["thread_id"], SUPERSEDED)
        store.add_pending(row)
    except Exception:
        _logger.warning("could not store the pending action", exc_info=True)


def record_choice(store: Any, row: dict[str, Any], outcome: str) -> None:
    """Mark the card the pending action came from as chosen, with what it did (as the API does for the button)."""
    try:
        message = store.message(row["message_id"])
        blocks = list((message or {}).get("blocks") or [])
        blocks[int(row["block"])] = {**blocks[int(row["block"])], "chosen": int(row["option"]), "outcome": outcome}
        store.set_blocks(row["message_id"], blocks)
    except Exception:
        _logger.warning("could not record the choice on its card", exc_info=True)
