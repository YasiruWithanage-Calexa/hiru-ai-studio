"""Implied steps, named and removable (plan/2026-11-01b Phase 3).

A script sometimes needs a step it does not write: the phone rings, and then a voice speaks from it.
Nobody answered. Veo is shown a voice that arrives from nowhere. A BRIDGE is that missing step, added
as an ordinary action block marked `implied`, so the picture clock counts it, the shot list can show
it, and a person can remove it.

The list is closed and rules-only. No model may add a bridge, and a bridge is never a line, never a
new person and never a story event:

* `answer_phone`   a ring, then a line marked as on the phone, with nobody answering in between
* `lower_phone`    a line on the phone, then an action by whoever holds it that does not put it down

A removed bridge is remembered on the phone line's script block (`skip_bridges`), so a re-split never
brings it back: a person's edit wins. Pure standard library (the `contracts` rule).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from contracts.shotplan import HEARD_MARKS, Item

ANSWER_PHONE = "answer_phone"
LOWER_PHONE = "lower_phone"
BRIDGES = (ANSWER_PHONE, LOWER_PHONE)

_PHONE_MARKS = tuple(m for m in HEARD_MARKS if "phone" in m)
_RING = re.compile(r"\b(?:phone|mobile|cell(?:phone)?)\b.*\b(?:rings?|rang|ringing|buzz(?:es|ed)?|vibrat\w+)\b|"
                   r"\b(?:rings?|rang|ringing)\b.*\b(?:phone|mobile)\b", re.IGNORECASE)
_ANSWERS = re.compile(
    r"\b(?:answer(?:s|ed|ing)?|pick(?:s|ed)?\s+(?:it\s+)?up|picks?\s+up|take(?:s|n)?\s+(?:the|her|his)\s+(?:call|phone)|"
    r"took\s+(?:the|her|his)\s+(?:call|phone)|lift(?:s|ed)?\s+(?:the|her|his)\s+phone|raise(?:s|d)?\s+(?:the|her|his)\s+"
    r"phone|accept(?:s|ed)?\s+the\s+call|put(?:s)?\s+(?:the|her|his)\s+phone\s+to|holds?\s+(?:the|her|his)\s+phone)\b",
    re.IGNORECASE)
_PUTS_DOWN = re.compile(
    r"\b(?:lower(?:s|ed)?|hang(?:s|ed)?\s+up|hung\s+up|end(?:s|ed)?\s+the\s+call|put(?:s)?\s+(?:the|her|his)\s+phone\s+"
    r"(?:down|away|in)|pocket(?:s|ed)?|drop(?:s|ped)?\s+(?:the|her|his)\s+phone|slip(?:s|ped)?\s+(?:the|her|his)\s+phone|"
    r"phone\b.*\b(?:down|away|pocket|bag))\b", re.IGNORECASE)
_PRONOUN_SUBJECT = re.compile(r"\b(she|he)\b|\b(her|his)\b", re.IGNORECASE)
_TEXTS = {ANSWER_PHONE: "{who} answers the phone.", LOWER_PHONE: "{who} lowers the phone."}


def is_phone_line(item: Item) -> bool:
    mark = f"{item.delivery} {item.speaker}".lower()
    return item.is_line and any(m in mark for m in _PHONE_MARKS)


def _names(items: Sequence[Item], exclude: Item, cast: Iterable[str] = ()) -> list[str]:
    """People who may hold the phone: whoever speaks in the scene and the production's cast (a
    person who never speaks is still in the picture), but not the one on the phone."""
    seen: list[str] = []
    for name in [*(i.speaker for i in items if i.is_line), *cast]:
        name = " ".join(str(name).split()).title()
        if name and name.casefold() != exclude.speaker.casefold() and name not in seen:
            seen.append(name)
    return seen


def holder_of(items: Sequence[Item], ring: int, phone_line: Item, cast: Iterable[str] = ()) -> str:
    """Who holds the phone, from the script alone: a name in the ring block, else the nearest name
    in the action blocks just before it, else a pronoun from the ring block, else nobody."""
    names = _names(items, phone_line, cast)
    ring_item = items[ring]
    for block in [ring_item, *[i for i in reversed(items[:ring]) if i.kind == "action"][:3]]:
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", block.text, re.IGNORECASE):
                return name
    match = _PRONOUN_SUBJECT.search(ring_item.text)
    if match:
        subject = (match.group(1) or match.group(2)).lower()
        return "She" if subject in ("she", "her") else "He"
    return ""


def _bridge(kind: str, holder: str, version: int) -> dict[str, Any]:
    text = _TEXTS[kind].format(who=holder) if holder else ("The call is answered." if kind == ANSWER_PHONE
                                                           else "The call ends.")
    return {"kind": "action", "text": text, "line_id": None, "implied": True, "by": "rules", "bridge": kind,
            "screen": "act", "events": 1, "for_version": version}


def plan_bridges(items: Sequence[Item], cast: Iterable[str] = ()) -> list[tuple[int, str, str]]:
    """→ [(insert before this item index, bridge kind, holder name)] in script order. `cast` is the
    production's character names, for a holder who never speaks in the scene."""
    cast = list(cast)
    out: list[tuple[int, str, str]] = []
    real = [i for i in items if not i.implied]  # judged as if no bridge were there
    pos = {i.index: n for n, i in enumerate(real)}
    for line in real:
        if not is_phone_line(line):
            continue
        n = pos[line.index]
        rings = [m for m in range(n - 1, -1, -1) if real[m].kind == "action" and _RING.search(real[m].text)]
        # The ring must come after the previous phone line (one call, one ring) and nobody answers it.
        previous = max((m for m in range(n) if is_phone_line(real[m])), default=-1)
        ring = next((m for m in rings if m > previous), None)
        holder = ""
        if ring is not None:
            holder = holder_of(real, ring, line, cast)
            between = " ".join(b.text for b in real[ring:n] if b.kind == "action")
            if ANSWER_PHONE not in line.skip and not _ANSWERS.search(between):
                out.append((line.index, ANSWER_PHONE, holder))
        after = real[n + 1] if n + 1 < len(real) else None
        if after is not None and after.kind == "action" and LOWER_PHONE not in line.skip:
            holder = holder or _holder_nearby(real, n, line, cast)
            if holder and _acts_for(after.text, holder) and not _PUTS_DOWN.search(after.text) \
                    and not is_phone_line(after):
                out.append((after.index, LOWER_PHONE, holder))
    return out


def _holder_nearby(real: Sequence[Item], n: int, line: Item, cast: Iterable[str] = ()) -> str:
    """The listener when no ring named the holder: a name in the action just after the call."""
    for name in _names(real, line, cast):
        if re.search(rf"\b{re.escape(name)}\b", real[n + 1].text, re.IGNORECASE):
            return name
    return ""


def _acts_for(text: str, holder: str) -> bool:
    if holder in ("She", "He"):
        return bool(_PRONOUN_SUBJECT.search(text))
    return bool(re.search(rf"\b{re.escape(holder)}\b", text, re.IGNORECASE) or _PRONOUN_SUBJECT.search(text))


def strip_bridges(script: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The script without the bridges the rules added (what a re-plan starts from). A bridge a
    person took over (`by` other than rules) stays."""
    return [dict(b) for b in script if not (b.get("implied") and b.get("by", "rules") == "rules")]


def with_bridges(script: Sequence[Mapping[str, Any]], lines: Sequence[Mapping[str, Any]], version: int,
                 cast: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The script with its implied steps in. Idempotent: bridges already there are recomputed, so
    editing the script (the person now writes "she answered") drops one that no longer applies."""
    from contracts.sceneplan import items_for  # local: keeps the module graph one-way

    base = strip_bridges(script)
    plans = plan_bridges(items_for(base, [dict(ln) for ln in lines]), cast)
    if not plans:
        return base
    # plan indexes are item indexes of `base`; map them to script positions (dangling lines are skipped)
    known = {str(ln["id"]) for ln in lines}
    position: dict[int, int] = {}
    n = 0
    for p, block in enumerate(base):
        if block.get("kind") == "dialogue" and str(block.get("line_id")) not in known:
            continue
        position[n] = p
        n += 1
    out = list(base)
    for index, kind, holder in sorted(plans, key=lambda t: position[t[0]], reverse=True):
        out.insert(position[index], _bridge(kind, holder, version))
    return out


def carry(old: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What the system keeps on blocks, carried across a person's edit of the script.

    A block the person left as it was (same kind and words, or the same line) keeps its reading and
    its implied mark. An implied step the person dropped or reworded is REMEMBERED as removed on the
    phone line it belonged to, so a re-split does not bring it back. Nothing is added."""
    from contracts.beats import BLOCK_EXTRA  # local: keep the module graph one-way

    pool: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for b in old:
        if b.get("kind") != "dialogue":
            pool.setdefault((str(b.get("kind")), str(b.get("text", ""))), []).append(b)
    by_line = {str(b.get("line_id")): b for b in old if b.get("kind") == "dialogue"}
    out: list[dict[str, Any]] = []
    for b in new:
        row = dict(b)
        if row.get("kind") == "dialogue":
            kept = by_line.get(str(row.get("line_id")))
            if kept is not None and kept.get("skip_bridges"):
                row["skip_bridges"] = list(kept["skip_bridges"])
        else:
            matches = pool.get((str(row.get("kind")), str(row.get("text", ""))))
            if matches:
                was = matches.pop(0)
                row |= {k: was[k] for k in BLOCK_EXTRA if k in was and k not in row}
        out.append(row)
    dropped = [id(m) for ms in pool.values() for m in ms]  # old blocks that no new block matched
    for position, b in enumerate(old):  # an implied step nobody kept
        if id(b) in dropped and b.get("implied") and b.get("bridge") in BRIDGES:
            around = old[position + 1:] if b["bridge"] == ANSWER_PHONE else list(reversed(old[:position]))
            anchor = next((str(o.get("line_id")) for o in around if o.get("kind") == "dialogue"), None)
            for row in out:
                if row.get("kind") == "dialogue" and str(row.get("line_id")) == anchor:
                    row["skip_bridges"] = sorted({*row.get("skip_bridges", []), str(b["bridge"])})
    return out


def skip_bridge(script: Sequence[Mapping[str, Any]], removed: int) -> list[dict[str, Any]]:
    """Remove the implied block at script position `removed` and remember it on the phone line that
    asked for it: the line after it (answer_phone) or the nearest phone line before it (lower_phone)."""
    rows = [dict(b) for b in script]
    block = rows[removed]
    kind = str(block.get("bridge") or "")
    if not block.get("implied") or kind not in BRIDGES:
        raise ValueError("that block is not an implied step")
    targets = range(removed + 1, len(rows)) if kind == ANSWER_PHONE else range(removed - 1, -1, -1)
    for p in targets:
        if rows[p].get("kind") == "dialogue":
            rows[p]["skip_bridges"] = sorted({*rows[p].get("skip_bridges", []), kind})
            break
    del rows[removed]
    return rows
