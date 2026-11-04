"""Which characters get looks drafted, and the rows to insert: the model's looks when they hold up, else the card's
wardrobe
split by rules. The model call is the `look_drafter` agent's; this is the code half. Ported from
`structure_build/engine/looks.py` (plan/2026-11-03 Phase 6)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from contracts.canon import LookFields, name_key
from contracts.lookdraft import by_rules, clean_proposals, look_row


def _card(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict((row.get("current") or {}).get("card") or {})


def wanted(canon: Sequence[Mapping[str, Any]], with_looks: set[str]) -> list[Mapping[str, Any]]:
    """Characters whose card has a wardrobe and who have no look yet."""
    return [c for c in canon if c.get("kind") == "character" and str(c["id"]) not in with_looks
            and str(_card(c).get("wardrobe") or "").strip()]


def asked_from(answer_looks: Sequence[Mapping[str, Any]], episodes: int) -> dict[str, list[LookFields]]:
    """name_key(character) -> the model's looks that hold up."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in answer_looks or []:
        grouped.setdefault(name_key(str(item.get("character") or "")), []).append(item)
    return {key: clean_proposals(items, episodes) for key, items in grouped.items()}


def characters_input(rows: Sequence[Mapping[str, Any]], episodes: int) -> dict[str, Any]:
    """The `look_drafter` agent's input for the characters `wanted` returned."""
    return {"episodes": max(episodes, 1), "characters": [{"name": str(r["name"]), "card": _card(r)} for r in rows]}


def rows_for(rows: Sequence[Mapping[str, Any]], asked: dict[str, list[LookFields]], episodes: int, *,
             production_id: str, actor: str | None) -> tuple[list[dict[str, Any]], list[str]]:
    """(look rows to insert, names of the characters that get them)."""
    out: list[dict[str, Any]] = []
    names: list[str] = []
    for row in rows:
        looks = asked.get(name_key(row["name"])) or by_rules(_card(row), episodes)
        if looks:
            names.append(str(row["name"]))
            out += [look_row(str(row["id"]), production_id, look, actor) for look in looks]
    return out, names
