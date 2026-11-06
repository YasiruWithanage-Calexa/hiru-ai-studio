"""Production memory: what a document says about HOW to make the drama (plan/2026-11-05d §4).

One entry is one instruction or fact about how the drama should look, sound, feel, be performed or be cut, with what it
applies to and the document's own words. It is a list, never a form: a production has the entries its documents gave and
no empty slots for what they did not.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
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
