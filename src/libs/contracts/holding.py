"""Who holds what, shot by shot: one holder per prop, read from the planner's staging marks.

A frame painted from words alone puts a prop in whichever hand is free: the phone at the ear of a woman who has just
dropped it, her umbrella in the hand of the man returning the phone, an umbrella held up by nothing while both hands
are on the phone. The planner already wrote who holds what (`Mark.holding`, "from this block on"); nothing carried it
to the image or the video prompt. This module does, the way PromptMotion's continuity ledger carries identity across
cuts (`nova_producer/engine/continuity.py`), with the prop state it never filled in.

    Ledger.of(marks)          every mark's holding → the changes: who takes a prop, from whom, who lets it go
    Ledger.at(block)          prop → (holder, thing) as block `block` opens; ONE holder per prop: a mark that gives a
                              prop to someone takes it from whoever had it (a planner that forgets to mark the giver
                              no longer leaves the phone in two hands)
    shot_hands(...)           the `Hands` of one shot: the sentence for the prompt and the line for the vision check

The state of a prop ("open", "folded") comes from the holding text, else from the last earlier sentence that puts the
prop in that state ("The umbrella snaps open.").

Pure standard library (the `contracts` rule). A scene with no marks that hold anything gives no ledger, so a frame of
any other scene is composed exactly as before.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# "—", "nothing": an empty hand, as planners write it
EMPTY = frozenset({"", "-", "—", "–", "nothing", "none", "empty", "empty-handed", "empty handed", "n/a", "no",
                   "free", "hands free"})
DETERMINERS = frozenset({"the", "a", "an", "her", "his", "their", "its", "my", "your", "our", "one", "some", "own"})
STATES: dict[str, str] = {"open": "open", "opened": "open", "opens": "open", "closed": "closed", "closes": "closed",
                          "shut": "closed", "folded": "folded", "folds": "folded", "furled": "folded"}
_STATE_WORDS = "|".join(sorted(STATES, key=len, reverse=True))
# Something carried that does not take a hand: a bag on the shoulder, a phone in a pocket
WORN = re.compile(r"\b(shoulder|pocket|worn|wearing|strap|slung|on (?:her|his|their) back|around (?:her|his|their))\b",
                  re.IGNORECASE)
# Carried on the shoulder unless the holding says it is in a hand
BAGS = re.compile(r"\b(handbag|bag|purse|backpack|satchel|rucksack|tote|sling)s?\b", re.IGNORECASE)
IN_HAND = re.compile(r"\bin (?:her|his|their|one) hand\b", re.IGNORECASE)
CLOSE = frozenset({"MCU", "CU", "ECU", "INSERT"})


@dataclass(frozen=True)
class Thing:
    """One thing in a person's hands, as the planner wrote it."""

    key: str  # what it is, to compare ("phone", "umbrella"): the head noun
    text: str  # how to say it, without an article ("open umbrella")
    state: str = ""  # open | closed | folded | "" (from the holding text)
    worn: bool = False  # carried without a hand (on the shoulder, in a pocket)


@dataclass(frozen=True)
class Change:
    """At `block`, `key` passes from `giver` to `taker` ("" = nobody: picked up, or let go)."""

    block: int
    key: str
    giver: str
    taker: str
    arrives: bool = False  # the person's first mark: they come into the scene with it, so it is theirs from the block's
    # start (Anudi steps out of the car holding the umbrella); any later change happens during its block


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'’-]*", text.lower())


def thing_of(text: str) -> Thing | None:
    """One holding item → a `Thing`; None for an empty hand."""
    raw = " ".join(str(text or "").split())
    clean = re.sub(r"\([^)]*\)", " ", raw).strip(" .,;:")
    if clean.lower() in EMPTY:
        return None
    worn = bool(WORN.search(raw)) or (bool(BAGS.search(raw)) and not IN_HAND.search(raw))
    # "phone at ear", "umbrella over her head": the thing is before the place it is held
    clean = re.split(r"\b(?:on|in|over|under|at|against|by|near|to|from|for)\b", clean, maxsplit=1)[0]
    # not the thing: an owner ("Anudi's phone"), a manner ("briefly"), a block number ("b6")
    words = [w for w in _words(clean) if w not in DETERMINERS and not re.search(r"['’]s$", w)
             and not (w.endswith("ly") and len(w) > 4) and not re.fullmatch(r"b\d+", w)]
    if not words:
        return None
    state = next((STATES[w] for w in words if w in STATES), "")
    body = [w for w in words if w not in STATES]
    if not body:
        return None
    if "of" in body[1:]:  # "cup of tea" is a cup
        body = body[: body.index("of")]
    key = re.sub(r"['’]s$", "", body[-1])
    text_words = [f"{state}"] if state else []
    return Thing(key=key, text=" ".join([*text_words, *body]), state=state, worn=worn)


def things_of(holding: str) -> list[Thing]:
    """A mark's `holding` ("umbrella, phone", "the phone and a bag", "—") → its things, each once."""
    parts = re.split(r",|;|&|\+|\band\b|\bwith\b|\bthen\b", str(holding or ""), flags=re.IGNORECASE)
    out: dict[str, Thing] = {}
    for p in parts:
        t = thing_of(p)
        if t is not None:
            out.setdefault(t.key, t)
    return list(out.values())


@dataclass
class Ledger:
    """Every holding change in a scene, in script order."""

    changes: list[Change] = field(default_factory=list)
    things: dict[str, Thing] = field(default_factory=dict)  # key → how the planner last wrote it
    # (block, who, key, left | right): a mark that names the hand (plan/2026-11-09); none for a planner's own marks
    sides: list[tuple[int, str, str, str]] = field(default_factory=list)

    @classmethod
    def of(cls, marks: Iterable[Mapping[str, Any]]) -> Ledger:
        marks = list(marks)
        rows = [(int(m.get("block") or 0), i, str(m.get("who") or "").strip(), str(m.get("holding") or ""))
                for i, m in enumerate(marks) if str(m.get("who") or "").strip()]
        rows.sort(key=lambda r: (r[0], r[1]))
        ledger = cls()
        for block, i, who, _ in rows:
            for side in ("left", "right"):
                thing = thing_of(str(marks[i].get(f"{side}_hand") or ""))
                if thing is not None:
                    ledger.sides.append((block, who, thing.key, side))
        holder: dict[str, str] = {}  # key → who has it now
        hands: dict[str, set[str]] = {}  # who → keys they hold now
        for block, _, who, holding in rows:
            first = who not in hands
            things = things_of(holding)
            now = {t.key for t in things}
            for t in things:
                ledger.things[t.key] = t
            mine = hands.setdefault(who, set())
            for key in sorted(mine - now):  # their new mark no longer has it: they let it go
                mine.discard(key)
                if holder.get(key) == who:
                    del holder[key]
                    ledger.changes.append(Change(block, key, who, ""))
            for key in sorted(now - mine):
                giver = holder.get(key, "")
                if giver and giver != who:
                    hands.get(giver, set()).discard(key)  # one holder: it leaves the giver's hand
                holder[key] = who
                mine.add(key)
                ledger.changes.append(Change(block, key, giver, who, arrives=first and not giver))
        ledger.changes = _handovers(ledger.changes)
        return ledger

    def __bool__(self) -> bool:
        return bool(self.changes)

    def at(self, block: int) -> dict[str, tuple[str, Thing]]:
        """key → (who holds it, how) as block `block` opens: the changes before it, and what a person arrives with at
        it."""
        holder: dict[str, str] = {}
        for c in self.changes:
            if c.block > block or (c.block == block and not c.arrives):
                continue
            if c.taker:
                holder[c.key] = c.taker
            elif holder.get(c.key) == c.giver:
                del holder[c.key]
        return {k: (who, self.things[k]) for k, who in holder.items()}

    def side(self, who: str, key: str, block: int) -> str:
        """The hand (left | right) `who` holds `key` in once block `block` has played: the latest mark that names the
        hand, since they took it; "" when no mark says."""
        took = max((c.block for c in self.changes if c.key == key and c.taker.casefold() == who.casefold()
                    and c.block <= block), default=None)
        if took is None:
            return ""
        said = [(b, s) for b, w, k, s in self.sides
                if k == key and w.casefold() == who.casefold() and took <= b <= block]
        return max(said)[1] if said else ""

    def during(self, start: int, end: int) -> list[Change]:
        return [c for c in self.changes if start <= c.block < end and not (c.block == start and c.arrives)]

    def knows(self, key: str) -> bool:
        return key in self.things


def _handovers(changes: list[Change]) -> list[Change]:
    """One block where the giver's mark comes first ("lets go") and the taker's second ("takes it from nobody") is ONE
    handover (plan/2026-11-09): the order of two marks at the same block says nothing."""
    out: list[Change] = []
    for c in changes:
        drop = next((i for i, d in enumerate(out) if d.block == c.block and d.key == c.key and d.giver and
                     not d.taker), None) if c.taker and not c.giver and not c.arrives else None
        if drop is not None:
            out[drop] = Change(c.block, c.key, out[drop].giver, c.taker)
        else:
            out.append(c)
    return out


def window(block_start: int, block_end: int) -> tuple[int, int]:
    """The blocks a shot plays. A shot with no block of its own (an insert, a reaction a director added) plays the
    moment of the block before it: the handover insert after "Anudi turns around" opens with the phone still his."""
    if block_end <= block_start and block_start > 0:
        return block_start - 1, block_start
    return block_start, block_end


def scene_marks(scene: Mapping[str, Any], planner: str = "") -> list[Mapping[str, Any]]:
    """The marks the planner of these shots wrote: Jonathan keeps them in its plan (`scenes.jonathan`), the others in
    the scene's staging map (`scenes.staging`)."""
    if planner == "jonathan":
        plan = ((scene.get("jonathan") or {}).get("plan") or {}) if isinstance(scene.get("jonathan"), Mapping) else {}
        marks = ((plan.get("staging") or {}).get("marks")) if isinstance(plan, Mapping) else None
    else:
        staging = scene.get("staging")
        marks = staging.get("marks") if isinstance(staging, Mapping) else None
    return [m for m in marks or [] if isinstance(m, Mapping)]


def state_in(key: str, texts: Iterable[str]) -> str:
    """The last state these sentences put `key` in ("The umbrella snaps open." → open), "" when none does."""
    found = ""
    near = r"(?:\s+\S+){0,3}?\s+"
    pattern = re.compile(rf"\b{re.escape(key)}s?\b{near}({_STATE_WORDS})\b|\b({_STATE_WORDS}){near}(?:the\s+)?"
                         rf"{re.escape(key)}s?\b", re.IGNORECASE)
    for text in texts:
        for sentence in re.split(r"(?<=[.!?;])\s+", str(text or "")):
            for m in pattern.finditer(sentence):
                found = STATES[(m.group(1) or m.group(2)).lower()]
    return found


@dataclass(frozen=True)
class Hands:
    """What one shot's prompt says about hands, and what the vision check is told to look for."""

    sentence: str = ""  # for the image or video prompt ("" = say nothing)
    expect: str = ""  # for the vision check ("" = nothing to check)
    held: dict[str, list[str]] = field(default_factory=dict)  # seen person → the keys they hold
    absent: list[str] = field(default_factory=list)  # keys held by someone not in the frame


def _say(t: Thing, state: str) -> str:
    words = t.text.split()
    if state and state not in words:
        words = [state, *words]
    return "the " + " ".join(words)


def _side_at(ledger: Ledger, now: dict[str, tuple[str, Thing]], key: str, start: int) -> str:
    """The hand the holder holds `key` in as the shot opens: what a mark says up to the block before it."""
    who = now.get(key, ("", None))[0]
    return (ledger.side(who, key, start - 1) or ledger.side(who, key, start)) if who else ""  # or they arrive with it


def _hand_words(side: str, default: str) -> str:
    return f"the {side} hand" if side else default


def _two_hands(a: str, b: str) -> tuple[str, str]:
    """The words for two hands: as the marks say them, else "one hand" and "the other hand" (as before)."""
    if a and b and a != b:
        return f"the {a} hand", f"the {b} hand"
    if a and not b:
        return f"the {a} hand", "the other hand"
    if b and not a:
        return "the other hand", f"the {b} hand"
    return "one hand", "the other hand"


def _either(things: Sequence[str]) -> str:
    if len(things) == 1:
        return things[0]
    return ", ".join(things[:-1]) + f" or {things[-1]}"


def shot_hands(ledger: Ledger | None, *, block_start: int, block_end: int, seen: Sequence[str], framing: str = "",
               earlier: Iterable[str] = (), video: bool = False, shown: str = "") -> Hands:
    """The hands of the people this shot SEES (their names, as the planner writes them), as the shot opens; with
    `video`, also what passes between hands during it. `earlier`: sentences before this shot, for a prop's state.
    `shown`: what the shot's own words show; a thing they name is never called "not in this frame" (the insert of the
    phone falling is the phone)."""
    if not ledger:
        return Hands()
    start, end = window(block_start, block_end)
    now = ledger.at(start)
    earlier = list(earlier)
    seen_keys = {s.casefold(): s for s in seen if s.strip()}
    by_person: dict[str, list[tuple[str, Thing]]] = {s: [] for s in seen_keys.values()}
    absent: list[str] = []
    for key, (who, thing) in sorted(now.items()):
        person = seen_keys.get(who.casefold())
        if person is None:
            if not thing.worn:  # a bag on someone's shoulder off screen is not a hand-held thing to keep out
                absent.append(key)
        else:
            by_person[person].append((key, thing))
    said: list[str] = []
    expect: list[str] = []
    for person, held in by_person.items():
        hand_held = [(k, t) for k, t in held if not t.worn]
        worn = [(k, t) for k, t in held if t.worn]
        names = [_say(t, t.state or state_in(k, earlier)) for k, t in hand_held]
        sides = [_side_at(ledger, now, k, start) for k, _ in hand_held]
        if not hand_held:
            # only what someone else holds right now: an empty hand is not news, a phone in two hands is the error
            others = [f"the {ledger.things[k].text.split()[-1]}" for k, (who, thing) in sorted(now.items())
                      if who.casefold() != person.casefold() and not thing.worn]
            if others:
                said.append(f"{person} is not holding {_either(others)}.")
                expect.append(f"{person} holds none of: {', '.join(others)}")
        elif len(names) == 1:
            said.append(f"{person} holds {names[0]} in {_hand_words(sides[0], 'one hand')}.")
            expect.append(f"{person} holds {names[0]}" + (f" in the {sides[0]} hand" if sides[0] else ""))
        else:
            rest = f", and also carries {', '.join(names[2:])}" if len(names) > 2 else ""
            first, second = _two_hands(sides[0], sides[1])
            said.append(f"{person} holds {names[0]} in {first} and {names[1]} in {second}{rest}; "
                        "each hand keeps its own, neither is put down.")
            expect.append(f"{person} holds {names[0]} and {names[1]}, one in each hand")
        for _, t in worn:
            said.append(f"{person} has {_say(t, t.state)}.")
    for key in absent:
        if re.search(rf"(?<!\w){re.escape(key)}s?(?!\w)", shown, re.IGNORECASE):
            continue  # the shot shows it (a hand in frame, an insert): its own words say how
        said.append(f"The {ledger.things[key].text.split()[-1]} is not in this frame.")
        expect.append(f"no {ledger.things[key].text.split()[-1]} visible")
    if framing.upper() in CLOSE and any(held for held in by_person.values()):
        said.append("Even this close, what each person holds stays in the picture (part of it in frame), "
                    "never left out.")
    if video:
        for c in ledger.during(start, end):
            giver, taker = seen_keys.get(c.giver.casefold()), seen_keys.get(c.taker.casefold())
            what = f"the {ledger.things[c.key].text.split()[-1]}"
            if giver and taker:
                said.append(f"During the shot {what} passes from {giver}'s hand to {taker}'s.")
            elif giver and not c.taker:
                said.append(f"During the shot {giver} lets go of {what}.")
            elif taker and not c.giver:
                said.append(f"During the shot {taker} takes {what}.")
    if not said:
        return Hands()
    held_keys = {p: [k for k, _ in h] for p, h in by_person.items() if h}
    return Hands(sentence="Hands: " + " ".join(said), expect="; ".join(expect), held=held_keys, absent=absent)


def canon_match(key: str, rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The production's prop this held thing is ("phone" → Smartphone): its name or an alias is the thing, or ends in
    it as a word or a compound ("smartphone"). The exact name wins; else the shortest name."""
    key = key.lower()
    found: list[tuple[int, int, Mapping[str, Any]]] = []
    for r in rows:
        if r.get("kind") != "prop":
            continue
        for name in [str(r.get("name") or ""), *[str(a) for a in r.get("aliases") or []]]:
            words = _words(name)
            if not words:
                continue
            if " ".join(words) == key:
                found.append((0, len(name), r))
            elif words[-1] == key or words[-1].endswith(key) or words[-1] == f"{key}s":
                found.append((1, len(name), r))
    found.sort(key=lambda f: (f[0], f[1]))
    return found[0][2] if found else None


_STOP = frozenset({"the", "a", "an", "of", "and", "s"})


def _name_words(name: str) -> list[str]:
    return [re.sub(r"['’]s$", "", w) for w in _words(name) if re.sub(r"['’]s$", "", w) not in _STOP]


def names_place(name: str, text: str) -> bool:
    """A place (or a fixed thing on it) is in this text: every word of its name, or all but one of a name of three
    words or more ("Kasun's Food Three-Wheeler" in "Stall (Kasun’s three-wheeler, frame left)")."""
    want = _name_words(name)
    have = set(_name_words(text))
    if not want:
        return False
    missing = [w for w in want if w not in have]
    return not missing or (len(want) >= 3 and len(missing) == 1 and want[-1] in have)


# ── one shot's frame: the hands, and which reference pictures it is painted against ─────────────────


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    return []


def picture_text(ir: Mapping[str, Any]) -> str:
    """What a shot's frame shows, in the author's words: the setting, the first frame and who the subjects are."""
    frame = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    subjects = [s.get("description") for s in ir.get("subjects") or [] if isinstance(s, Mapping)]
    return " \n ".join([*_texts(ir.get("setting")), *_texts(frame), *[str(s or "") for s in subjects]])


def earlier_text(scene: Mapping[str, Any], shot: Mapping[str, Any]) -> list[str]:
    """The sentences before this shot, for a prop's state: the script's actions before its first block, then what
    Jonathan's earlier shots say happens ("The umbrella snaps open.")."""
    start, _ = window(int(shot.get("block_start") or 0), int(shot.get("block_end") or 0))
    script = [str(b.get("text") or "") for i, b in enumerate(scene.get("script") or [])
              if isinstance(b, Mapping) and b.get("kind") == "action" and i < start]
    plan = (scene.get("jonathan") or {}).get("plan") if isinstance(scene.get("jonathan"), Mapping) else None
    number = int(shot.get("number") or 0)
    planned = [t for s in ((plan or {}).get("shots") or []) if isinstance(s, Mapping) and int(s.get("n") or 0) < number
               for b in ((s.get("ir") or {}).get("beats") or []) if isinstance(b, Mapping)
               for t in _texts(b.get("action"))] if str(shot.get("planner") or "") == "jonathan" else []
    return [*script, *planned]


def ledger_for(scene: Mapping[str, Any], shot: Mapping[str, Any]) -> Ledger:
    return Ledger.of(scene_marks(scene, str(shot.get("planner") or "")))


def hands_for(scene: Mapping[str, Any], shot: Mapping[str, Any], seen: Sequence[str], *,
              video: bool = False) -> Hands:
    """The `Hands` of a stored shot, for the people it SEES (their names)."""
    return shot_hands(ledger_for(scene, shot), block_start=int(shot.get("block_start") or 0),
                      block_end=int(shot.get("block_end") or 0), seen=seen, framing=str(shot.get("framing") or ""),
                      earlier=earlier_text(scene, shot), video=video, shown=shown_text(shot))


def shown_text(shot: Mapping[str, Any]) -> str:
    """What a stored shot's own words show: its picture and its beats' actions."""
    ir = shot.get("ir") if isinstance(shot.get("ir"), Mapping) else {}
    beats = [t for b in (ir or {}).get("beats") or [] if isinstance(b, Mapping) for t in _texts(b.get("action"))]
    return " \n ".join([picture_text(ir or {}), *beats])


def zones_at(marks: Sequence[Mapping[str, Any]], block: int, people: Sequence[str]) -> list[str]:
    """Where these people stand as `block` opens (their latest mark before it)."""
    out: list[str] = []
    for who in people:
        mine = sorted((int(m.get("block") or 0), str(m.get("zone") or "")) for m in marks
                      if str(m.get("who") or "").casefold() == who.casefold() and int(m.get("block") or 0) < block)
        if not mine:
            mine = sorted((int(m.get("block") or 0), str(m.get("zone") or "")) for m in marks
                          if str(m.get("who") or "").casefold() == who.casefold())[:1]
        if mine and mine[-1][1]:
            out.append(mine[-1][1])
    return out


def references_for(scene: Mapping[str, Any], shot: Mapping[str, Any], canon: Sequence[Mapping[str, Any]],
                   base: Sequence[str], seen: Mapping[str, str], *, removed: Iterable[str] = (),
                   has_sheet: Any = None) -> list[tuple[str, str]]:
    """The canon ids a frame is painted against, in order, each with a note for its label ("held by Anudi"):

    1. `base` as it stands (the people seen, the scene's place, what a person added), except a PROP the ledger knows
       that is not in this frame: held by someone off screen, or lying nowhere this shot shows. A person's addition of
       the phone to every shot no longer puts the phone in every hand.
    2. after the scene's place, any other place of the production this shot is at, by its name in the shot's words or
       where its people stand (the stall a scene on a road keeps returning to);
    3. a prop someone seen holds, that has a sheet and is not there yet.

    `seen`: canon id → name of the people the camera sees. `has_sheet(row)`: whether a row has a picture (a place or
    prop without one is not added; one already in `base` stays, as before). Nothing changes for a scene whose planner
    wrote no holdings and names no other place."""
    by_id = {str(c["id"]): c for c in canon}
    removed = set(removed)
    sheet = has_sheet or (lambda row: True)
    names = list(seen.values())
    ledger = ledger_for(scene, shot)
    start, _ = window(int(shot.get("block_start") or 0), int(shot.get("block_end") or 0))
    now = ledger.at(start) if ledger else {}
    ir = shot.get("ir") if isinstance(shot.get("ir"), Mapping) else {}
    words = picture_text(ir or {})
    seen_folded = {n.casefold(): n for n in names}

    def prop_key(row: Mapping[str, Any]) -> str:
        return next((k for k in ledger.things if canon_match(k, [row]) is row), "") if ledger else ""

    out: list[tuple[str, str]] = []
    for cid in base:
        row = by_id.get(cid)
        if row is None:
            continue
        if row.get("kind") == "prop":
            key = prop_key(row)
            if key:
                holder = now.get(key, ("", None))[0]
                if holder and holder.casefold() in seen_folded:
                    out.append((cid, f"held by {seen_folded[holder.casefold()]}"))
                elif not holder and re.search(rf"\b{re.escape(key)}s?\b", words, re.IGNORECASE):
                    out.append((cid, ""))
                continue  # held off screen, or not in this frame
        out.append((cid, ""))
    place = str(scene.get("location_id") or "")
    # other places go right after the scene's place (else after the people)
    ids = [cid for cid, _ in out]
    people = sum(1 for c in ids if (by_id.get(c) or {}).get("kind") == "character")
    at = ids.index(place) + 1 if place in ids else people
    where = " \n ".join([words, *zones_at(scene_marks(scene, str(shot.get("planner") or "")), start, names)])
    have = {cid for cid, _ in out}
    extra = [(str(r["id"]), "") for r in canon if r.get("kind") == "location" and str(r["id"]) not in have
             and str(r["id"]) not in removed and str(r["id"]) != place and sheet(r)
             and names_place(str(r.get("name") or ""), where)]
    out[at:at] = extra
    have |= {cid for cid, _ in extra}
    for key, (holder, _) in sorted(now.items()):
        person = seen_folded.get(holder.casefold())
        row = canon_match(key, canon) if person else None
        if row is not None and str(row["id"]) not in have and str(row["id"]) not in removed and sheet(row):
            out.append((str(row["id"]), f"held by {person}"))
            have.add(str(row["id"]))
    return out
