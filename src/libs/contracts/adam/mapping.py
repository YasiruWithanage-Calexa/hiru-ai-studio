"""A ShotCard → the existing `shots` row, so everything after the plan keeps working (plan/2026-11-04b §5.1).

`shots.framing` keeps its seven values (WIDE, MS, MCU, CU, TWO, OTS, INSERT); the full card goes in `shots.card`.

    size + arrangement → framing   ECU→CU · EWS/WS/MWS→WIDE · POV→MCU (INSERT when the size is INSERT) · GROUP→WIDE
    take_s             → duration_s
    the card's moments → block_start, block_end   (the script range it belongs to; end is exclusive, as in `shots`)
    cut_in.link        → camera_link

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from contracts.adam.plan import Moment, ShotCard

FRAMINGS: tuple[str, ...] = ("WIDE", "MS", "MCU", "CU", "TWO", "OTS", "INSERT")
_BY_SIZE = {"EWS": "WIDE", "WS": "WIDE", "MWS": "WIDE", "MS": "MS", "MCU": "MCU", "CU": "CU", "ECU": "CU",
            "INSERT": "INSERT"}
_BY_ARRANGEMENT = {"two": "TWO", "ots": "OTS", "group": "WIDE", "pov": "MCU"}


def framing_of(size: str, arrangement: str = "single") -> str:
    """The `shots.framing` value for a card. An INSERT is an insert whatever the arrangement."""
    if size == "INSERT":
        return "INSERT"
    return _BY_ARRANGEMENT.get(arrangement) or _BY_SIZE[size]


def block_range(card: ShotCard, moments: Sequence[Moment], fallback: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    """(first block, one past the last) of the script this card presents, from its moments. An elaboration that
    serves a block counts too, so the card sits where the story is; a card with none keeps `fallback`."""
    by_id = {m.id: m for m in moments}
    blocks = sorted({b for ident in card.moments if (m := by_id.get(ident)) for b in m.blocks})
    return (blocks[0], blocks[-1] + 1) if blocks else fallback


def card_to_row(card: ShotCard, moments: Sequence[Moment], *, fallback: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    """The fields of the `shots` row a card decides. Ids, `scene_id`, the beats and the bound lines are the
    writer's (`adam_write`); this is only the mapping, so it can be tested without a database."""
    start, end = block_range(card, moments, fallback)
    return {
        "number": card.number,
        "title": card.title,
        "framing": framing_of(card.size, card.arrangement),
        "duration_s": card.take_s,
        "block_start": start,
        "block_end": end,
        "camera_link": card.cut_in.link,
        "planner": "adam",
        "card": card.model_dump(mode="json", by_alias=True),
    }
