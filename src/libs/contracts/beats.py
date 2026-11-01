"""Reading a script as pictures (plan/2026-11-01b Phase 2).

Every ACTION block in a scene's script is read once per script version: how it shows up on screen
(`screen`: see `contracts.timing.SCREEN_SECONDS`) and how many visible events it holds (`events`).
The kernel's picture clock (`contracts.shotplan`) is built on it.

* move       a move through space (runs, walks away, drives, crosses ...): needs room to be seen
* act        one thing the camera can show
* with_line  a small action that plays under the line after it (a smile, a look, a nod)
* info       information the camera must carry another way (an insert, a line, a look):
             "It was her father."
* inner      a thought or a fact nobody can film: "He had no idea this would change his life."

This module is the free, deterministic reading (also the fallback when there is no model key, and
what the director's chat uses after a person edits a block). `script_split/engine/beats.py` asks a
model for a better reading and falls back to this one block by block. A reading never rewrites a
block. Pure standard library (the `contracts` rule).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from contracts.shotplan import Item
from contracts.timing import SCREEN_KINDS

MAX_EVENTS = 6
# What an action block may carry beyond its text: how it reads as a picture, whether the system added it
# (`contracts.bridges`), and the script version it was read for. A dialogue block may carry `skip_bridges`.
BLOCK_EXTRA = ("screen", "events", "implied", "by", "for_version", "bridge")

_ABBREVIATIONS = ("rs", "mr", "mrs", "ms", "dr", "st", "no", "vs", "etc", "a.m", "p.m")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z])")
_THEN = re.compile(r"\b(?:and then|then|before)\b", re.IGNORECASE)

# Order matters: a block that reads as a thought is not filmed, whatever else it says.
_INNER = re.compile(
    r"\b(?:had no idea|has no idea|have no idea|no idea that|didn'?t know|did not know|doesn'?t know|"
    r"thought|thinks|thinking|knew|knows|wondered|wonders|felt|feels|feeling|wished|hoped|hopes|realised|"
    r"realized|remembered|remembers|would change|will change|about to change|was about to|"
    r"little did)\b", re.IGNORECASE)
_INFO = re.compile(r"^\W*(?:it|this|that|there)\s*(?:'s|is|was|were|are)\b|\((?:voice only|v\.?o\.?|o\.?s\.?)\)",
                   re.IGNORECASE)
_MOVE = re.compile(
    r"\b(?:run|runs|ran|running|rush|rushes|rushed|hurry|hurries|hurried|chase|chases|chased|"
    r"walk|walks|walked|walking|drive|drives|drove|driving|ride|rides|rode|cross|crosses|crossed|"
    r"climb|climbs|climbed|enter|enters|entered|exit|exits|exited|leave|arrive|arrives|"
    r"arrived|approach|approaches|approached|follow|follows|followed|storm|storms|stormed|"
    r"race|races|raced|dash|dashes|dashed|step(?:s|ped)? (?:out|in|away|back|forward|inside)|"
    r"head(?:s|ed)? (?:out|off|away|home|to))\b", re.IGNORECASE)
_REACTION = re.compile(
    r"\b(?:smile|smiles|smiled|smiling|look|looks|looked|looking|glance|glances|glanced|turn|turns|turned|"
    r"nod|nods|nodded|frown|frowns|frowned|sigh|sighs|sighed|laugh|laughs|laughed|grin|grins|grinned|"
    r"shrug|shrugs|shrugged|hesitate|hesitates|hesitated|pause|pauses|paused|blink|blinks|blinked|"
    r"swallow|swallows|swallowed|stare|stares|stared|wince|winces|winced|breathe|breathes|breathed|"
    r"clear(?:s|ed)? (?:her|his|their) throat)\b", re.IGNORECASE)
_PRONOUN = re.compile(r"\b(?:she|he|her|his|they|their)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Reading:
    screen: str
    events: int


def sentences(text: str) -> list[str]:
    """The sentences of an action paragraph, in order and verbatim ("Rs. 5,000" and "Mr. Perera"
    do not end one). Nothing is added or dropped: joined with spaces they are the paragraph."""
    clean = " ".join(text.split())
    merged: list[str] = []
    for part in _SENTENCE_END.split(clean) if clean else []:
        if merged and merged[-1].rstrip(".").rsplit(" ", 1)[-1].lower().rstrip(".") in _ABBREVIATIONS:
            merged[-1] += " " + part
        else:
            merged.append(part)
    return merged


def events_in(text: str) -> int:
    """How many visible events a block holds: its sentences, plus a "... and then ..." inside one."""
    merged = sentences(text)
    count = len([p for p in merged if re.search(r"\w", p)]) or 1
    count += sum(len(_THEN.findall(p)) for p in merged)
    return min(MAX_EVENTS, count)


def read_block(text: str, nxt: Item | None = None) -> Reading:
    """One action block by rules. `nxt` is the block right after it (a line makes a small action
    play under it).

    A block is read sentence by sentence: a thought or a piece of information is not filmed, so it
    only makes the whole block "inner" / "info" when nothing else is in it; otherwise the sentences
    that ARE filmed set the block's events and screen kind."""
    parts = sentences(text) or [text]
    inner = [bool(_INNER.search(p)) for p in parts]
    info = [bool(_INFO.search(p)) and not x for p, x in zip(parts, inner, strict=True)]
    filmed = [p for p, x, i in zip(parts, inner, info, strict=True) if not x and not i]
    if not filmed:
        return Reading("inner" if any(inner) else "info", 1)
    events = min(MAX_EVENTS, len(filmed) + sum(len(_THEN.findall(p)) for p in filmed))
    body = " ".join(filmed)
    if _MOVE.search(body):
        return Reading("move", events)
    if nxt is not None and nxt.is_line and _REACTION.search(body) and events == 1:
        who = (nxt.speaker or "").split(" ")[0].casefold()
        # "Anudi smiles." before Kasun's line is not under his line; "She looked at Kasun" before hers is.
        if _PRONOUN.search(body) or (who and who in body.casefold()):
            return Reading("with_line", 1)
    return Reading("act", events)


def read_by_rules(items: Sequence[Item]) -> dict[int, Reading]:
    """Item index → reading, for every action block that a person has not already marked."""
    out: dict[int, Reading] = {}
    for n, item in enumerate(items):
        if item.kind != "action" or item.implied or item.by == "person":
            continue
        nxt = items[n + 1] if n + 1 < len(items) else None
        out[item.index] = read_block(item.text, nxt)
    return out


def is_stale(items: Sequence[Item], version: int) -> bool:
    """Does any action block still need a reading for this script version?"""
    return any(i.kind == "action" and not i.implied and i.by != "person" and i.for_version != version
               for i in items)


def annotate(script: Sequence[Mapping[str, Any]], lines: Sequence[Mapping[str, Any]],
             readings: Mapping[int, Reading], version: int, by: str) -> list[dict[str, Any]]:
    """The script blocks with the readings written onto the action blocks they belong to.

    `readings` is keyed by the kernel item index (`sceneplan.items_for` drops a dialogue block
    whose line is gone, so an item index is not always the block's position)."""
    known = {str(ln["id"]) for ln in lines}
    out: list[dict[str, Any]] = []
    index = 0
    for block in script:
        row = dict(block)
        if row.get("kind") == "dialogue" and str(row.get("line_id")) not in known:
            out.append(row)  # a dangling reference: kept as stored, not an item
            continue
        reading = readings.get(index)
        if row.get("kind") == "action" and reading is not None:
            row |= {"screen": _screen(reading.screen), "events": max(1, min(MAX_EVENTS, int(reading.events))),
                    "by": by, "for_version": version}
        out.append(row)
        index += 1
    return out


def _screen(value: str) -> str:
    return value if value in SCREEN_KINDS else "act"
