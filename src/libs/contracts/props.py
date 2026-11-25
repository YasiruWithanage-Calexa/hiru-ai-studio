"""Props: one roster per scene, every prop on a board panel bound to its own sheet (plan/2026-11-25b; lab/prop_mapping,
approach A).

The Scene board paints every prop as a white clay stand-in (plan/2026-11-23c). A first frame painted from the panel
was told only "paint every one as the real prop from its reference sheet": no image number, no holder, and only the
props the ledger holds had a sheet attached. Scene 4 shot 11 came out with a white umbrella (the clay's colour), a
second, folded umbrella from the look sheet, and a dark phone whose sheet is orange. The lab's approach A fixed every
fault with words and sheets alone:

    scene_props(...)   the props of a scene, ONE list for the board and the frame: the canon props the plans name (the
                       old `Board.props` rule), the ones the ledger knows, and the ones a person carries in their look
                       or the scene's condition (Anudi's umbrella and handbag)
    bind(...)          each prop a panel shows, resolved against that list only, never the whole canon ("bag" is the
                       handbag a person carries, never another scene's document bag), with its holder, hand, side and
                       state
    binding_text(...)  the lab's paragraph (`lab/prop_mapping/run.py` `roster_words`): each stand-in tied to its image
                       number by holder, hand and side; "white is never a prop's colour"; "each prop appears once"
    PROPS_SLOT         the line `contracts.board.frame_sections` leaves where that paragraph goes: the frame's compose
                       fills it once the attached pictures are numbered, so a number never points at the wrong picture

The words are the lab's; the changes made to take them from one scene to any scene are listed in
plan/2026-11-25b/IMPLEMENTED.md (C1-C5). Pure: rows in, words out.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from contracts import holding
from contracts.canon import named_in

Source = Literal["prop", "look", "words"]

# The line `frame_sections` leaves for the props paragraph (filled by the frame's compose, `fill_slot`).
PROPS_SLOT = "<the props of this panel, bound to their sheets>"
# The most prop sheets one frame painted from a panel takes ON TOP of `frame_brief.MAX_REFERENCES` (the lab sent 3 with
# 6 other pictures and the panel: 10 in all; the image model takes up to 16; quality falls as pictures are added).
MAX_PANEL_PROPS = 4
SHEET_HEAD = "the reference sheet for "
PANEL = "The approved scene board panel"
DRAFT = "The approved draft"


@dataclass(frozen=True)
class RosterProp:
    """One prop of a scene. `key`: its canon id, or "words:<name>" for a thing with no card. `name`: the ONE name used
    for it everywhere (the canon name). `look`: what it looks like (the first sentence of the card's `details`)."""

    key: str
    name: str
    look: str = ""
    source: Source = "prop"
    aliases: tuple[str, ...] = ()

    @property
    def canon_id(self) -> str:
        return "" if self.key.startswith("words:") else self.key


@dataclass(frozen=True)
class BoundProp:
    """One stand-in of a panel, resolved to its roster prop. `said`: the writer's name for it ("tea flask")."""

    prop: RosterProp
    said: str
    holder: str = ""
    hand: str = ""  # left | right | both | "" (worn, or resting)
    rests_on: str = ""
    side: str = ""  # left | right | centre
    state: str = ""  # open | closed | folded | ""
    colour: str = ""  # the holder's mannequin colour


@dataclass(frozen=True)
class Bound:
    """A panel's bound props, with what the frame's words need beside them."""

    props: list[BoundProp] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.props)

    def canon_ids(self) -> list[str]:
        return [b.prop.canon_id for b in self.props if b.prop.canon_id]


# ── the roster ──────────────────────────────────────────────────────────────────────────────────────────────


def _names(row: Mapping[str, Any]) -> list[str]:
    return [n for n in [str(row.get("name") or ""), *(str(a) for a in row.get("aliases") or [])] if n]


def look_of(row: Mapping[str, Any]) -> str:
    """What a prop looks like, for the frame (C3): the first sentence of its card's `details` (the umbrella's second
    sentence says when it is open or closed, which is the shot's to say), with a leading "A" made lower case so it
    reads inside a sentence and any ";" made ",". "" when the card says nothing."""
    card = ((row.get("current") or {}).get("card") or {}) if isinstance(row.get("current"), Mapping) else {}
    text = " ".join(str(card.get("details") or "").split())
    if not text:
        return ""
    # a ";" inside it would read as the break between two props of the roster sentence
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].rstrip(" .").replace(";", ",")
    return re.sub(r"^(A|An|The)\b", lambda m: m.group(1).lower(), first)


def scene_props(canon: Sequence[Mapping[str, Any]], texts: Iterable[str], things: Iterable[str] = (),
                carried: Iterable[str] = ()) -> list[RosterProp]:
    """The props of a scene, in canon order, each once (§2.1):

    1. a canon prop the shots' words name, by name or alias, or as the end of a word of four letters or more the words
       use ("smartphone"): the rule `Board.props` had (plan/2026-11-23c §3.3);
    2. a canon prop the ledger knows (`things`: the ledger's keys, matched by `holding.canon_match`);
    3. a canon prop a person carries (`carried`: their look's accessories and the scene's condition), by its whole
       name or alias ("tan handbag" names the handbag, never the bag).
    """
    props = [c for c in canon if c.get("kind") == "prop"]
    text = " \n ".join(str(t or "") for t in texts)
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", text)}
    source: dict[str, Source] = {}
    for c in props:
        if any(named_in(n, text) for n in _names(c)) or any(
                holding.canon_match(w, [c]) is not None for w in words if len(w) >= 4):
            source.setdefault(str(c["id"]), "prop")
    for key in things:
        row = holding.canon_match(str(key), props)
        if row is not None:
            source.setdefault(str(row["id"]), "prop")
    worn = " \n ".join(str(t or "") for t in carried)
    for c in props:
        if worn and any(named_in(n, worn) for n in _names(c)):
            source.setdefault(str(c["id"]), "look")
    return [RosterProp(key=str(c["id"]), name=str(c.get("name") or ""), look=look_of(c), source=source[str(c["id"])],
                       aliases=tuple(str(a) for a in c.get("aliases") or []))
            for c in props if str(c["id"]) in source]


# ── one panel's stand-ins ───────────────────────────────────────────────────────────────────────────────────


def bare(name: str) -> str:
    """A stand-in's name without "the", "a" or "clay" in front."""
    return re.sub(r"^(?:the |a |an )?(?:white )?(?:clay )?", "", " ".join(str(name or "").split()),
                  flags=re.IGNORECASE).strip(" .")


def resolve(said: str, roster: Sequence[RosterProp], others: Sequence[RosterProp] = ()) -> RosterProp | None:
    """The roster prop a stand-in is: its name or an alias exactly, else by `holding.canon_match` on the whole name,
    then on its last word ("tea flask" → flask; "bag" → the handbag when the handbag is on the roster). Only when the
    roster has none: one of `others` (the production's other props, `canon_props`) whose name or alias IS the stand-in's
    name or its last word, never a longer name ending in it (a flask only the panel shows; never "bag" → handbag).
    None: not a prop of this production."""
    key = bare(said).lower()
    if not key:
        return None
    words = list(dict.fromkeys([key, key.split()[-1]]))
    rows = [{"kind": "prop", "name": p.name, "aliases": list(p.aliases), "key": p.key} for p in roster]
    by_key = {p.key: p for p in roster}
    for word in words:
        row = holding.canon_match(word, rows)
        if row is not None:
            return by_key[str(row["key"])]
    for word in words:
        found = next((p for p in others if any(n.lower() == word for n in (p.name, *p.aliases))), None)
        if found is not None:
            return found
    return None


def canon_props(canon: Sequence[Mapping[str, Any]]) -> list[RosterProp]:
    """Every prop of the production as a `RosterProp` (source `prop`): what `resolve` falls back on."""
    return [RosterProp(key=str(c["id"]), name=str(c.get("name") or ""), look=look_of(c),
                       aliases=tuple(str(a) for a in c.get("aliases") or [])) for c in canon if c.get("kind") == "prop"]


_OPEN_HAND = re.compile(r"\b(?:open(?:ed)?\s+(?:palms?|hands?|fingers?)|(?:palms?|hands?|fingers?)\s+(?:held\s+)?"
                        r"open(?:ed)?)\b", re.IGNORECASE)


def bind(panel_props: Sequence[Mapping[str, Any]], roster: Sequence[RosterProp],
         colours: Mapping[str, str] | None = None, texts: Sequence[str] = (), others: Sequence[RosterProp] = ()
         ) -> Bound:
    """The panel's stand-ins (`PanelProp` as stored: name, held_by, hand, rests_on, frame_side), each resolved against
    the roster, then by exact name against `others` (`resolve`); one that is neither is a words-only prop under the
    writer's own name, never dropped. Two
    stand-ins of one prop are one. `texts`: the words that may give a prop's state (the shot's words, the panel's,
    the ledger's), the last one wins (`holding.state_in`). `colours`: person name → mannequin colour."""
    out: list[BoundProp] = []
    seen: set[str] = set()
    # an open palm or hand is never a prop's state ("palm open beneath the clay phone" read as an open phone, phase 6)
    plain = [_OPEN_HAND.sub(" ", str(t or "")) for t in texts]
    for raw in panel_props:
        said = bare(str(raw.get("name") or ""))
        if not said:
            continue
        found = resolve(said, roster, others) or RosterProp(key=f"words:{said.lower()}", name=said, source="words")
        if found.key in seen:
            continue
        seen.add(found.key)
        holder = " ".join(str(raw.get("held_by") or "").split())
        state = ""
        for word in dict.fromkeys([said.split()[-1].lower(), found.name.split()[-1].lower()]):
            state = holding.state_in(word, plain) or state
        out.append(BoundProp(prop=found, said=said, holder=holder, hand=str(raw.get("hand") or "").strip().lower(),
                             rests_on=" ".join(str(raw.get("rests_on") or "").split()).rstrip("."),
                             side=str(raw.get("frame_side") or "").strip().lower(), state=state,
                             colour=str((colours or {}).get(holder) or "")))
    return Bound(props=out)


_PREPOSITION = re.compile(r"^(?:on|in|over|from|under|at|across|by|against|beside|inside|hanging|through|between|"
                          r"around|along|near|upon|atop|behind)\b", re.IGNORECASE)
_SIDES = {"centre": "at the centre of the frame", "center": "at the centre of the frame", "left": "at frame left",
          "right": "at frame right"}


def _resting(text: str) -> str:
    said = re.sub(r"^(The|A|An)\b", lambda m: m.group(1).lower(), text.strip())
    return said if _PREPOSITION.match(said) else f"on {said}"


def where_words(b: BoundProp) -> str:
    """Where the stand-in is on the panel, in people's names (C1: built from the writer's fields; the lab's were
    written by hand): "the clay umbrella in Anudi's left hand (the blue mannequin's), at frame right"; "the clay
    handbag Anudi carries, on Anudi's left forearm, at frame right"; "the clay tea flask resting on the serving ledge,
    at frame left"."""
    thing = f"the clay {b.said}"
    mannequin = f" (the {b.colour} mannequin's)" if b.colour else ""
    if b.holder and b.hand in ("left", "right"):
        at = f"{thing} in {b.holder}'s {b.hand} hand{mannequin}"
    elif b.holder and b.hand == "both":
        at = f"{thing} in both of {b.holder}'s hands{mannequin}"
    elif b.holder:
        at = f"{thing} {b.holder} carries" + (f", {_resting(b.rests_on)}" if b.rests_on else "")
    else:
        at = f"{thing} resting" + (f" {_resting(b.rests_on)}" if b.rests_on else "")
    side = _SIDES.get(b.side, "")
    return f"{at}, {side}" if side else at


def _the(name: str) -> str:
    return name if re.match(r"^(?:the|a|an)\s", name, re.IGNORECASE) else f"the {name}"


def _and(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def once_line(bound: Bound, looks: Mapping[str, str]) -> str:
    """"Each prop appears once" (C2: the lab named Anudi's umbrella and handbag by hand): for each person whose look
    sheet is attached (`looks`: name → what their look carries), the bound props their look names are the same
    things, never a second one."""
    bits = []
    for person, carried in looks.items():
        mine = [b.prop.name for b in bound.props if b.prop.source != "words"
                and any(named_in(n, carried) for n in (b.prop.name, *b.prop.aliases) if n)]
        if not mine:
            continue
        verb = "are these same things" if len(mine) > 1 else "is this same thing"
        bits.append(f"{_and([_the(n) for n in mine])} on {person}'s look sheet {verb}, never a second "
                    + " or ".join(mine))
    return "Each prop appears once" + (": " + "; ".join(bits) if bits else "") + "."


def binding_text(bound: Bound, image_of: Mapping[str, int], once: str = "Each prop appears once.",
                 subject: str = PANEL) -> str:
    """The lab's paragraph (`roster_words`, approach A) in place of `contracts.board.PROP_STAND_INS`. `image_of`: canon
    id → the number of its attached sheet; a prop with none is painted from its look words. `subject`: `PANEL` for a
    frame painted from its shot prompt with the panel as the blocking, `DRAFT` for one with the panel as its draft."""
    owner = "the panel's" if subject == PANEL else "the draft's"
    bits = []
    for b in bound.props:
        state = f", {b.state}" if b.state else ""
        n = image_of.get(b.prop.canon_id) if b.prop.canon_id else None
        if n:
            what = f"paint it exactly as image {n} shows it" + (f" ({b.prop.look})" if b.prop.look else "") + state
        else:
            what = f"it has no picture: paint {b.prop.look or _the(b.prop.name)}{state}"
        bits.append(f"{where_words(b)} is {_the(b.prop.name)}: {what}")
    return (f"{subject} shows the props as plain white clay stand-ins. White is never a prop's colour: each stand-in "
            "marks only where a real prop is, its size, its angle and the hand that holds it. These are the props, "
            "each exactly once: " + "; ".join(bits) + f". {once} Keep {owner} layout, proportions and perspective for "
            "every prop; add no other prop. No white clay shape, blank object or unfinished prop remains in the frame.")


def image_numbers(labels: Sequence[str], bound: Bound) -> dict[str, int]:
    """Canon id → the number of its attached sheet, read from the labels as attached ("the reference sheet for
    umbrella" is image 7)."""
    by_name = {b.prop.name.casefold(): b.prop.canon_id for b in bound.props if b.prop.canon_id}
    out: dict[str, int] = {}
    for n, label in enumerate(labels, start=1):
        if label.startswith(SHEET_HEAD):
            cid = by_name.get(re.sub(r"\s*\(.*\)$", "", label[len(SHEET_HEAD):]).strip().casefold())
            if cid and cid not in out:
                out[cid] = n
    return out


def prop_looks(bound: Bound) -> dict[str, str]:
    """Prop name → its look words, for the attached sheets' jobs (`frame_brief.reference_job`)."""
    return {b.prop.name: b.prop.look for b in bound.props if b.prop.canon_id}


__all__ = [
    "DRAFT",
    "MAX_PANEL_PROPS",
    "PANEL",
    "PROPS_SLOT",
    "SHEET_HEAD",
    "Bound",
    "BoundProp",
    "RosterProp",
    "bare",
    "bind",
    "binding_text",
    "canon_props",
    "image_numbers",
    "look_of",
    "once_line",
    "prop_looks",
    "resolve",
    "scene_props",
    "where_words",
]
