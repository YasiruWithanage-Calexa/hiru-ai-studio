"""Zora's guards (plan/2026-11-06e §4.8): what the old director chat learned in plan/2026-11-01c, COPIED from
`steps/scene_kernel` (`proposals.py`, `loop.py`, `turn_logic.py`) and changed to read Zora's ledger, so the old chat
can be removed whole later without touching Zora.

    confirms(message) / agrees(message)   "i confirm", "do it", "apply it": answered in code, never by a model
    undo_asked(message)                   "undo that", "go back", "redo": a revision is restored in code, no model
    goal_of / repeated                    the loop breaker: the same unmet request twice is answered, not retried
    guard_reply(text, …)                  a reply sentence that cannot stand goes: a card that is not there, an offer
                                          to do something later when nothing waits, a change claimed when the ledger
                                          shows none, an offer to trim a line (Hiru: never trimmed)
    template_reply(ledger, …)             the reply in code, from the same ledger, when no model can write it
    cannot_text(cannot)                   why a request is not possible here, and where it can be done

Pure standard library + pydantic.
"""
from __future__ import annotations

import re
from typing import Any

from contracts.zora.ledger import Ledger

# ── confirmations (copied from scene_kernel/proposals.py) ────────────────────────────────────────────────────────

_FOLLOW = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|yes|yeah|yep|sure|please|right|great|good)\b[\s,.!-]*)*"
    r"(?:(?:do|apply|use|try|take|go with|go for|make|add)\s+(?:that|this|it|those|these)"
    r"(?:\s+(?:one|too|please|(?:right\s+)?now))*"
    r"|go ahead(?:\s+and\s+(?:do|apply)\s+(?:it|that))?|please do|do it|i\s+confirm(?:\s+it)?|confirm(?:ed)?"
    r"|that(?:'s| is)? (?:good|great|right|fine)(?:,?\s*do it)?"
    r"|(?:yes|yeah|yep|sure|ok(?:ay)?))"
    r"(?:\s+(?:please|now|too|then))*[\s.!,]*$", re.I)
_CONFIRM_TAIL = re.compile(r"(?:^|[\s,.;:-])(?:and\s+)?i\s+confirm(?:\s+it)?[\s.!]*$", re.I)
_BARE_YES = re.compile(r"^\s*(?:(?:ok(?:ay)?|yes|yeah|yep|sure|please|right|great|good)\b[\s,.!-]*)+$", re.I)

NOTHING_WAITING = "There is nothing waiting to apply."


def agrees(message: str) -> bool:
    """Could the message be a "yes" to something waiting? What it agrees to is found in code."""
    return bool(_FOLLOW.match(message or "")) or bool(_CONFIRM_TAIL.search(message or ""))


def confirms(message: str) -> bool:
    """An explicit confirmation ("i confirm it", "do it", "apply it"). A bare "yes" is not: it may only be a reply."""
    return agrees(message) and not _BARE_YES.match(message or "")


# ── undo and redo (new in Zora: G7) ──────────────────────────────────────────────────────────────────────────────

_UNDO = re.compile(r"^\s*(?:please\s+)?(?:undo|revert|go back|take (?:that|it) back|put (?:it|that) back)"
                   r"(?:\s+(?:that|this|it|the last (?:change|edit|one)|what you (?:just )?did))?"
                   r"(?:\s+please)?[\s.!]*$", re.I)
_REDO = re.compile(r"^\s*(?:please\s+)?(?:redo|re-do|put it back again|do it again)(?:\s+(?:that|it))?"
                   r"(?:\s+please)?[\s.!]*$", re.I)


def undo_asked(message: str) -> str:
    """→ "undo", "redo" or "": a whole message that asks for the last change undone (or the undo undone)."""
    if _UNDO.match(message or ""):
        return "undo"
    if _REDO.match(message or ""):
        return "redo"
    return ""


# ── the loop breaker (copied from scene_kernel/loop.py) ──────────────────────────────────────────────────────────

AGAIN = "Asking again will not change that."


def cannot_goal(cannot: dict[str, str]) -> str:
    """One goal per way out: the same route is the same unmet need, however the request was worded."""
    return "cannot:" + " ".join(re.sub(r"[^a-z0-9→ ]+", " ", str(cannot.get("route") or "").lower()).split())[:60]


def goal_of(message: dict[str, Any]) -> tuple[str, bool]:
    """→ (goal, met) a director reply recorded, ("", True) when it had none."""
    for block in message.get("blocks") or []:
        if block.get("kind") == "text" and block.get("goal"):
            return str(block["goal"]), block.get("met") is True
    return "", True


def repeated(history: list[dict[str, Any]], goal: str) -> bool:
    """Is `goal` the one the director's last replies left unmet? A met one, or a card chosen on, ends the run."""
    if not goal:
        return False
    run = 0
    for message in reversed(history):
        if message.get("kind") != "director":
            continue
        earlier, met = goal_of(message)
        if earlier != goal:
            break
        if met or any(b.get("kind") == "options" and b.get("chosen") is not None for b in message.get("blocks") or []):
            return False
        run += 1
    return run > 0


def cannot_text(cannot: dict[str, str]) -> str:
    reason = str(cannot.get("reason") or "That is not something this chat can change.").rstrip(".")
    route = str(cannot.get("route") or "").strip()
    return f"{reason}." + (f" {route[:1].upper()}{route[1:].rstrip('.')}." if route else "")


# ── the reply guard (copied from scene_kernel/proposals.py, reading the ledger) ──────────────────────────────────

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_CARD_TALK = re.compile(
    r"\b(?:apply|choose|pick|select|click|tap|accept|take|see|find|use|shown|listed)\b[^.!?\n]{0,40}\bbelow\b"
    r"|\bbelow\b[^.!?\n]{0,25}\b(?:apply|choose|options?|cards?|buttons?)\b"
    r"|\b(?:the|this|these|those|each|an?)\s+(?:options?\s+)?cards?\b"
    r"|\b(?:under|beneath)\s+(?:this|my|the)\s+(?:reply|message)\b", re.I)
_PROMISE = re.compile(
    r"\bconfirm\b[^.!?\n]{0,40}\b(?:and|then)\b[^.!?\n]{0,20}\b(?:we|i)(?:'ll|\s+will|\s+can|\s+could)\b"
    r"|\bonce you (?:confirm|say)\b|\bsay the word\b|\bready to (?:apply|switch|go|make|do)\b"
    r"|\b(?:i|we)(?:'ll|\s+will)\s+(?:apply|switch|translate|change|make|do|put|update)\b"
    r"|\bwhen you(?:'re| are) ready\b|\bjust (?:say|confirm|tell me)\b", re.I)
_CLAIM = re.compile(
    r"\balready (?:applied|done|made|changed|switched|updated|in place)\b"
    r"|\b(?:has|have|had)(?: already)? been (?:applied|changed|switched|updated|made|done|moved|added|removed)\b"
    r"|\b(?:i|we)(?:'ve| have) (?:applied|changed|switched|made|updated|translated|put|moved|added|removed|"
    r"rewritten|tightened|adjusted|reworked|set)\b"
    r"|^\s*(?:all )?done\b", re.I)
_NEGATED = re.compile(r"\b(?:no|not|nothing|never|none|nor)\b|n't\b", re.I)
# Hiru never trims a line: an offer to shorten one is the model's, never the code's, and it goes.
_TRIM = re.compile(r"\b(?:i|we)(?:'ll|\s+will|\s+can|\s+could)\s+(?:trim|shorten|cut down|tighten)\b[^.!?\n]{0,40}"
                   r"\b(?:line|dialogue|words)\b", re.I)
NO_RECEIPT = "Nothing in the plan changed this turn."


def guard_reply(text: str, ledger: Ledger, *, has_card: bool = False, pending: bool = False) -> str:
    """The reply without any sentence that cannot stand. May come back empty (every sentence went): the caller then
    writes the template reply."""
    kept: list[str] = []
    changed = replaced = False
    for sentence in _SENTENCE.split(text):
        if not sentence.strip():
            continue
        if (not has_card and _CARD_TALK.search(sentence)) or (not (has_card or pending) and _PROMISE.search(sentence)) \
                or _TRIM.search(sentence):
            changed = True
            continue
        if ledger.nothing_changed and _CLAIM.search(sentence) and not _NEGATED.search(sentence):
            changed = True
            if not replaced:
                kept.append(NO_RECEIPT)
                replaced = True
            continue
        kept.append(sentence.strip())
    return " ".join(kept) if changed else text


def template_reply(ledger: Ledger, *, fact: str = "") -> str:
    """The reply in code, from the ledger: what a person must know, in the ledger's order."""
    parts: list[str] = [fact] if fact else []
    if ledger.offer:
        parts.append(f"{ledger.offer} Re-plan the scene with Jonathan? The plan is as it was.")
    elif ledger.changes:
        shown = "; ".join(f"{c.where}: {c.text}" for c in ledger.changes[:6])
        more = len(ledger.changes) - 6
        parts.append(f"Changed: {shown}" + (f"; and {more} more." if more > 0 else "."))
    elif ledger.attempted:
        parts.append("Nothing in the plan changed.")
    for label, items in (("Not applied", ledger.refused), ("Asked for, not done yet", ledger.undelivered),
                         ("Waiting for you", ledger.staged)):
        if items:
            parts.append(f"{label}: " + "; ".join(items[:4]) + ".")
    if ledger.overruns:
        parts.append(ledger.overruns[0])
    if ledger.seams:
        parts.append(f"The next scene no longer starts where this one ends: {ledger.seams[0]}")
    return " ".join(p.strip() for p in parts if p.strip()) or "Nothing in the plan changed."
