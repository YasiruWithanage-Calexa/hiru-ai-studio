"""Production memory: what a document says about HOW to make the drama (plan/2026-11-05d §4).

One entry is one instruction or fact about how the drama should look, sound, feel, be performed or be cut, with what it
applies to and the document's own words. It is a list, never a form: a production has the entries its documents gave and
no empty slots for what they did not.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# What the reader is OFFERED. A topic is open text; this is only the list a first-time reader and a panel start from.
STARTER_TOPICS = ("series", "tone", "visual", "camera", "lighting", "sound", "music", "edit", "performance",
                  "language", "rule")
Strength = Literal["must", "prefer", "fact"]  # a rule ("only", "never") · a style · a fact (genre, tagline, setting)
Status = Literal["draft", "approved", "rejected"]
Source = Literal["reader", "person"]
STRENGTHS: tuple[str, ...] = ("must", "prefer", "fact")
MAX_TOPIC = 40

# `applies_to`: "production", or "<kind>:<value>" with one of these kinds.
SCOPES = ("place", "character", "episode", "when")


class MemoryEntry(BaseModel):
    """A row of `production_memory`."""

    model_config = ConfigDict(extra="forbid")

    id: UUID | None = None
    production_id: UUID | None = None
    topic: str
    applies_to: str = "production"
    says: str
    quote: str = ""
    strength: Strength = "prefer"
    document_id: UUID | None = None
    status: Status = "draft"
    source: Source = "reader"
    created_at: datetime | None = None


def topic_key(topic: str) -> str:
    """A topic as it is stored and subscribed to: lower case, words joined by `_`, at most MAX_TOPIC characters."""
    return "_".join(str(topic).casefold().split())[:MAX_TOPIC]


def parse_target(applies_to: str) -> tuple[str, str] | None:
    """`applies_to` as (kind, value): ("production", ""), ("place", "Colombo"), ("episode", "2") ... None when it is
    not one of the five forms (an `episode` needs a whole number; every other kind needs words)."""
    text = " ".join(str(applies_to).split())
    if text.casefold() == "production":
        return "production", ""
    kind, colon, value = text.partition(":")
    kind, value = kind.strip().casefold(), value.strip()
    if not colon or kind not in SCOPES or not value:
        return None
    if kind == "episode" and not (value.isdigit() and int(value) > 0):
        return None
    return kind, value


def target_text(applies_to: str) -> str:
    """The stored form of a valid target ("Place: Colombo " → "place:Colombo"); "" when it is not valid."""
    parsed = parse_target(applies_to)
    if parsed is None:
        return ""
    kind, value = parsed
    return kind if kind == "production" else f"{kind}:{value}"


def _genre_rank(row: Mapping[str, Any]) -> int:
    """A person's own row first, then an approved one, then a reader's draft."""
    if row.get("source") == "person":
        return 0
    return 1 if row.get("status") == "approved" else 2


def genre_of(rows: Iterable[Mapping[str, Any]]) -> str:
    """The production's genre as a short phrase a picture prompt can carry ("action and crime thriller"), from its
    `series` facts (plan/2026-11-12b): the genre row a person wrote or approved first, else the reader's draft; never a
    rejected row. The row says `Genre: action, crime thriller; love as a thread. ...` (`contracts.breakdown.series.
    genre_line`): the facets before the first `;` or `.` are kept, at most two. A person may write just "family drama".
    "" when there is none, or it holds a number or a gated word: the prompts then keep their general wording."""
    from contracts.breakdown.series import phrase

    found = [r for r in rows if topic_key(str(r.get("topic") or "")) == "series" and r.get("status") != "rejected"
             and target_text(str(r.get("applies_to") or "")) == "production"
             and "genre" in f"{r.get('says') or ''} {r.get('quote') or ''}".casefold()]
    for row in sorted(found, key=_genre_rank):
        says = " ".join(str(row.get("says") or "").split())
        head, colon, rest = says.partition(":")
        text = rest if colon and head.strip().casefold() == "genre" else says
        text = text.split(";", 1)[0].split(".", 1)[0]
        got = phrase([f.strip().casefold() for f in text.split(",")])
        if got:
            return got
    return ""
