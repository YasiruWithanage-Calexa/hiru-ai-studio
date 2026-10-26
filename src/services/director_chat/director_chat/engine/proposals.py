"""Follow-ups to the director's own advice (PLAN.md v2 §7 "do that" and Phase 0 "proposal ledger").

"Update S02 with that", "yes", "do it": the person is answering something the director said. What
they mean is in the director's last message, either an options card still waiting for a choice or
plain advice in its reply text. The turn resolves the reference here, in code, from the stored
thread, so a follow-up never depends on a model finding the right words in the chat history, and
never ends as a chat-only answer that promises a card which does not exist.

Also the reply guard: a reply may only point at a card ("apply it below") when the message
carries one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# A short answer to advice: "yes", "do that", "apply it", "update S02 with that", "go ahead".
_FOLLOW = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|yes|yeah|yep|sure|please|right|great|good)\b[\s,.!-]*)*"
    r"(?:(?:do|apply|use|try|take|go with|go for|make|add)\s+(?:that|this|it|those|these)(?:\s+(?:one|too|please|now))*"
    r"|go ahead|please do|do it|that(?:'s| is)? (?:good|great|right|fine)(?:,?\s*do it)?"
    r"|(?:update|change|fix|redo|apply|put|set|rework)\b[^.?!\n]{0,60}?\b(?:with|using|like|as|per)\s+(?:that|this|it)"
    r"(?:\s+(?:advice|suggestion|idea|note))?"
    r"|(?:yes|yeah|yep|sure|ok(?:ay)?))"
    r"(?:\s+(?:please|now|too|then))*(?:\s+(?:for|on|in|to)\s+[^.?!\n]{1,40})?[\s.!,]*$", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
# Words that point at a card, or at something under the reply ("apply this below"). A plain
# "below" ("below the envelope") is not one.
_CARD_TALK = re.compile(
    r"\b(?:apply|choose|pick|select|click|tap|accept|take|see|find|use|shown|listed)\b[^.!?\n]{0,40}\bbelow\b"
    r"|\bbelow\b[^.!?\n]{0,25}\b(?:apply|choose|options?|cards?|buttons?)\b"
    r"|\b(?:the|this|these|those|each|an?)\s+(?:options?\s+)?cards?\b"
    r"|\b(?:under|beneath)\s+(?:this|my|the)\s+(?:reply|message)\b", re.I)
MIN_ADVICE_CHARS = 20


@dataclass(frozen=True)
class Advice:
    """What a follow-up refers to: `card` (an options card still waiting for a choice) or `text`
    (advice in a reply, with no structured change behind it)."""

    kind: str
    text: str


def refers_back(message: str) -> bool:
    """Is this message a short answer to the director's last suggestion?"""
    return bool(_FOLLOW.match(message or ""))


def _reply_text(message: dict[str, Any]) -> str:
    return " ".join(str(b.get("text", "")) for b in message.get("blocks") or [] if b.get("kind") == "text").strip()


def _open_card(message: dict[str, Any]) -> bool:
    return any(b.get("kind") == "options" and b.get("chosen") is None
               and any(o.get("ops") or o.get("prompt") for o in b.get("options") or [])
               for b in message.get("blocks") or [])


def latest_advice(history: list[dict[str, Any]]) -> Advice | None:
    """The director's most recent message, as something to follow up. A message with a card is
    settled once a choice was made on it (nothing is left to follow up); notes the board left
    about an error carry no advice and are passed over."""
    for message in reversed(history):
        if message.get("kind") != "director":
            continue
        if any(b.get("kind") == "options" for b in message.get("blocks") or []):
            return Advice("card", _reply_text(message)) if _open_card(message) else None
        text = _reply_text(message)
        if len(text) >= MIN_ADVICE_CHARS:
            return Advice("text", text)
    return None


def guard_reply(text: str, *, has_card: bool) -> str:
    """The reply without any sentence that points at a card the message does not carry. May be
    empty (the whole reply was about the card): the caller then writes the plain reply."""
    if has_card or not _CARD_TALK.search(text):
        return text
    kept = [s for s in _SENTENCE.split(text) if s.strip() and not _CARD_TALK.search(s)]
    return " ".join(s.strip() for s in kept)
