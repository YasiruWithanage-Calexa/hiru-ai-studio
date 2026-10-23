"""Candidates → rows. Pure: decides what to create, version or leave alone; the store writes it.

* A LOCKED entity is never changed; the report says what extraction would have changed.
* An existing entity gets a new version only when its card actually changed (card hash).
* When the current version was written by a PERSON, extraction only fills fields that are
  still empty: a person's wording is never overwritten by a re-extraction.
* Codes from the documents are kept when free; everything else gets the lowest free code.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from canon_extract.engine import rules
from canon_extract.engine.rules import Candidate
from contracts.canon import (
    CanonCard,
    CanonKind,
    name_key,
    next_code,
    reference_sheet_prompt,
    voice_pin,
    wardrobe_anchor,
)

Row = dict[str, Any]


@dataclass
class Plan:
    creates: list[tuple[Row, Row]] = field(default_factory=list)  # (entity, version 1)
    versions: list[tuple[str, Row, Row]] = field(default_factory=list)  # (entity id, version, entity fields)
    updates: list[tuple[str, Row]] = field(default_factory=list)  # identity-only changes
    locked: list[str] = field(default_factory=list)  # codes left alone because they are locked
    unchanged: int = 0


def clean_card(card: dict[str, Any]) -> CanonCard:
    """Known fields only, whitespace collapsed, cut to each field's limit."""
    values: dict[str, str] = {}
    for name, info in CanonCard.model_fields.items():
        limit = next((m.max_length for m in info.metadata if getattr(m, "max_length", None)), 2000)
        values[name] = " ".join(str(card.get(name) or "").split())[:limit]
    return CanonCard(**values)


def card_hash(card: CanonCard) -> str:
    return hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def version_row(entity_id: str, production_id: str, number: int, kind: CanonKind, name: str, card: CanonCard,
                aspect_ratio: str, actor: str | None) -> Row:
    character = kind is CanonKind.CHARACTER
    return {"id": str(uuid4()), "entity_id": entity_id, "production_id": production_id, "version": number,
            "card": card.model_dump(), "card_hash": card_hash(card),
            "wardrobe_anchor": wardrobe_anchor(card) if character else "",
            "voice_pin": voice_pin(card) if character else "",
            "reference_prompt": reference_sheet_prompt(kind, name, card, aspect_ratio=aspect_ratio),
            "source": "extract", "created_by": actor}


def _existing_as_candidate(row: Row) -> Candidate:
    return rules.candidate(CanonKind(row["kind"]), row["name"], code=row["code"],
                           aliases=list(row.get("aliases") or []))


def plan(cands: list[Candidate], existing: list[Row], *, production_id: str, aspect_ratio: str,
         actor: str | None) -> Plan:
    out = Plan()
    taken = {str(r["code"]) for r in existing}
    matched: set[str] = set()
    for cand in cands:
        kind = CanonKind(cand["kind"])
        row = next((r for r in existing if str(r["id"]) not in matched
                    and rules.same(_existing_as_candidate(r), cand)), None)
        card = clean_card(cand["card"])
        if row is None:
            code = cand["code"] if cand["code"] and cand["code"] not in taken else next_code(kind, taken)
            taken.add(code)
            entity_id = str(uuid4())
            entity = {"id": entity_id, "production_id": production_id, "kind": kind.value, "code": code,
                      "name": cand["name"][:120], "aliases": cand["aliases"][:20], "core": bool(cand["core"])}
            out.creates.append((entity, version_row(entity_id, production_id, 1, kind, cand["name"], card,
                                                    aspect_ratio, actor)))
            continue
        matched.add(str(row["id"]))
        if row.get("locked"):
            out.locked.append(str(row["code"]))
            continue
        current = row.get("current") or {}
        old = clean_card(current.get("card") or {})
        if current.get("source") == "user":  # fill gaps only
            new = old.model_copy(update={k: v for k, v in card.model_dump().items() if v and not getattr(old, k)})
        else:
            new = old.model_copy(update={k: v for k, v in card.model_dump().items() if v})
        aliases = list(dict.fromkeys([*(row.get("aliases") or []), *cand["aliases"]]))
        aliases = [a for a in aliases if name_key(a) != name_key(row["name"])][:20]
        identity: Row = {}
        if aliases != list(row.get("aliases") or []):
            identity["aliases"] = aliases
        if cand["core"] and not row.get("core"):
            identity["core"] = True
        if card_hash(new) != current.get("card_hash"):
            number = int(current.get("version") or 0) + 1
            out.versions.append((str(row["id"]), version_row(str(row["id"]), production_id, number, kind,
                                                             row["name"], new, aspect_ratio, actor), identity))
        elif identity:
            out.updates.append((str(row["id"]), identity))
        else:
            out.unchanged += 1
    return out


def critic(cands: list[Candidate]) -> list[str]:
    """What a person should fill in before shots are written. Free and deterministic."""
    notes = []
    for c in cands:
        if c["kind"] != CanonKind.CHARACTER.value or not c["core"]:
            continue
        wanted = (("wardrobe", "wardrobe anchor"), ("voice", "voice"))
        missing = [label for key, label in wanted if not c["card"].get(key)]
        if missing:
            notes.append(f"{c['code'] or c['name']}: no {' or '.join(missing)} in the documents yet.")
    return notes
