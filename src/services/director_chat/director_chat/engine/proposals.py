"""Follow-ups to the director's own advice (PLAN.md v2 §7 "do that" and Phase 0 "proposal ledger").

"Update S02 with that", "yes", "do it": the person is answering something the director said. What
they mean is in the director's last message, either an options card still waiting for a choice or
plain advice in its reply text. The turn resolves the reference here, in code, from the stored
thread, so a follow-up never depends on a model finding the right words in the chat history, and
never ends as a chat-only answer that promises a card which does not exist.

Also the reply guard (plan/2026-11-01c): a reply may only point at a card ("apply it below") when
the message carries one, may only offer to do something later ("say the word", "confirm and we'll
switch") when a card or a pending action is waiting, and may only say a change was made when this
turn's receipts, a chosen card's recorded effect or the scene itself show it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contracts import director_capabilities as caps

# A short answer to advice: "yes", "do that", "apply it", "update S02 with that", "go ahead".
_FOLLOW = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|yes|yeah|yep|sure|please|right|great|good)\b[\s,.!-]*)*"
    r"(?:(?:do|apply|use|try|take|go with|go for|make|add)\s+(?:that|this|it|those|these)"
    r"(?:\s+(?:one|too|please|(?:right\s+)?now))*"
    r"|go ahead(?:\s+and\s+(?:do|apply)\s+(?:it|that))?|please do|do it|i\s+confirm(?:\s+it)?|confirm(?:ed)?"
    r"|that(?:'s| is)? (?:good|great|right|fine)(?:,?\s*do it)?"
    r"|(?:update|change|fix|redo|apply|put|set|rework)\b[^.?!\n]{0,60}?\b(?:with|using|like|as|per)\s+(?:that|this|it)"
    r"(?:\s+(?:advice|suggestion|idea|note))?"
    r"|(?:yes|yeah|yep|sure|ok(?:ay)?))"
    r"(?:\s+(?:please|now|too|then))*(?:\s+(?:for|on|in|to)\s+[^.?!\n]{1,40})?[\s.!,]*$", re.I)
# "…, i confirm it": a confirmation closing a longer message ("keep all other settings, i confirm it").
_CONFIRM_TAIL = re.compile(r"(?:^|[\s,.;:-])(?:and\s+)?i\s+confirm(?:\s+it)?[\s.!]*$", re.I)
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


_BARE_YES = re.compile(r"^\s*(?:(?:ok(?:ay)?|yes|yeah|yep|sure|please|right|great|good)\b[\s,.!-]*)+$", re.I)


def agrees(message: str) -> bool:
    """Could the message be a "yes" to something waiting ("yes", "do it", "i confirm it", "apply it")?
    What it agrees to is found in code: a pending action, else the director's last advice, else nothing."""
    return refers_back(message) or bool(_CONFIRM_TAIL.search(message or ""))


def confirms(message: str) -> bool:
    """An explicit confirmation ("i confirm it", "do it right now", "apply it"): with nothing waiting it
    is answered "There is nothing waiting to apply." A bare "yes" or "ok" is not: it may only be a reply."""
    return agrees(message) and not _BARE_YES.match(message or "")


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
        if any(b.get("kind") == "text" and b.get("advice") is False for b in message.get("blocks") or []):
            return None  # a refusal or "nothing is waiting": there is nothing in it to follow up
        text = _reply_text(message)
        if len(text) >= MIN_ADVICE_CHARS:
            return Advice("text", text)
    return None


def last_route(history: list[dict[str, Any]]) -> str:
    """Where the person can get their last unmet request done (the `route` on the director's latest
    message), "" when that message did not carry one."""
    for message in reversed(history):
        if message.get("kind") == "director":
            return next((str(b["route"]) for b in message.get("blocks") or []
                         if b.get("kind") == "text" and b.get("route")), "")
    return ""


# An offer to do something LATER: nothing can be confirmed unless a card or a pending action is waiting.
_PROMISE = re.compile(
    r"\bconfirm\b[^.!?\n]{0,40}\b(?:and|then)\b[^.!?\n]{0,20}\b(?:we|i)(?:'ll|\s+will|\s+can|\s+could)\b"
    r"|\bonce you (?:confirm|say)\b|\bsay the word\b|\bready to (?:apply|switch|go|make|do)\b"
    r"|\b(?:i|we)(?:'ll|\s+will)\s+(?:apply|switch|translate|change|make|do|put|update)\b"
    r"|\bwhen you(?:'re| are) ready\b|\bjust (?:say|confirm|tell me)\b", re.I)
# Every language the registry can check (Sinhala, Tamil, Hindi, English), by any of its names.
_LANG = "|".join(re.escape(a) for a in sorted((a for lang in caps.LANGUAGES for a in lang.aliases), key=len,
                                               reverse=True))
_LANG_NAME = re.compile(rf"(?<!\w)(?:{_LANG})(?!\w)", re.I)
_LANG_TARGET = re.compile(rf"\b(?:to|into|in)\s+(?:the\s+)?((?:{_LANG}))(?!\w)", re.I)
# A sentence that says a change WAS made. "S02 is now 8 s" is a statement of state, not of this: only a past
# change ("already applied", "has been switched", "I've changed") or a bare "Done" counts.
_CLAIM = re.compile(
    r"\balready (?:applied|done|made|changed|switched|updated|in place)\b"
    r"|\b(?:has|have|had)(?: already)? been (?:applied|changed|switched|updated|made|done)\b"
    r"|\b(?:i|we)(?:'ve| have) (?:applied|changed|switched|made|updated|translated|put)\b"
    rf"|\b(?:dialogues?|lines?|everything)\b[^.!?]{{0,30}}\b(?:now|already)\b[^.!?]{{0,20}}(?<!\w)(?:{_LANG})(?!\w)"
    r"|^\s*(?:all )?done\b", re.I)
# "Nothing has been applied" says no change was made: it is the honest answer, not a claim to check.
_NEGATED = re.compile(r"\b(?:no|not|nothing|never|none|nor)\b|n't\b", re.I)
_DIALOGUE_TALK = re.compile(rf"(?<!\w)(?:{_LANG})(?!\w)|\bdialogues?\b|\blines?\b|\bwords\b", re.I)
NO_RECEIPT = "Nothing was applied by this message."


@dataclass(frozen=True)
class Receipts:
    """What backs a reply that says something was changed: this turn's applied operations, the recorded
    effect of cards the person chose, and the scene's dialogue as it is now ("si", "en", "mixed", "none")."""

    applied: bool = False
    applied_dialogue: bool = False
    effects: tuple[str, ...] = field(default_factory=tuple)
    dialogue: str = "none"


def claimed_language(sentence: str) -> caps.Language | None:
    """The language a sentence says the lines are in now: the one after "to / into / in" ("switched from English to
    Tamil"), else the last one it names. None when it names none."""
    found = _LANG_TARGET.findall(sentence) or _LANG_NAME.findall(sentence)
    return caps.language_named(found[-1]) if found else None


def claim_backed(sentence: str, r: Receipts) -> bool:
    if _DIALOGUE_TALK.search(sentence):
        lang = claimed_language(sentence)
        return (r.applied_dialogue or any("changed dialogue" in e.lower() for e in r.effects)
                or bool(lang and r.dialogue == lang.code))
    return r.applied or any(e.lower().startswith(("applied", "changed")) for e in r.effects)


def guard_reply(text: str, *, has_card: bool, pending: bool = False, receipts: Receipts | None = None,
                state_fact: str = "") -> str:
    """The reply without any sentence that cannot stand. Dropped: a sentence that points at a card the
    message does not carry, and one that offers to do something later when no card or pending action
    waits. Replaced (once) by `state_fact`: a sentence that says a change was made when `receipts`
    do not show it. May be empty (the whole reply went): the caller then writes the plain reply."""
    kept: list[str] = []
    changed = False
    replaced = False
    for sentence in _SENTENCE.split(text):
        if not sentence.strip():
            continue
        if (not has_card and _CARD_TALK.search(sentence)) or (
                not (has_card or pending) and _PROMISE.search(sentence)):
            changed = True
            continue
        if receipts is not None and _CLAIM.search(sentence) and not _NEGATED.search(sentence) and not claim_backed(
                sentence, receipts):
            changed = True
            if not replaced:
                kept.append(state_fact or NO_RECEIPT)
                replaced = True
            continue
        kept.append(sentence.strip())
    return " ".join(kept) if changed else text
