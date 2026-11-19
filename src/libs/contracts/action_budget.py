"""The action budget of one clip (plan/2026-11-18c, proven in lab/action_budget).

A clip is counted in ACTIONS, never in seconds: its length follows from how long its action takes (the person,
2026-11-18). Raphael owns the breakdown; `contracts.raphael.checks.action_budget` hands an over-budget clip back to it.

- HARD: a change of state the video model has to invent (a door opens or closes, a person gets out of a car, sits down
  or stands up, a thing is taken, put, passed, poured, dropped or falls, an umbrella opens, a vehicle stops).
- MOVE: a simple visible movement (walks off, turns, looks, nods, smiles, leans, reaches).
- A state ("keeps", "remains", "still in her hand", "continues walking") is not an action.
- TRAVEL: a person crossing the frame or walking off, read on the whole beat (states included).

Over budget: more than `HARD_MAX` hard actions, more than `ALL_MAX` actions in all, or a hard action while someone
travels. Checked over 572 Raphael clips: every clip the person judged bad broke it, every good one kept it.

Two scene-level faults ride with it: a door opened (or already open) that no clip closes, and a clip with a spoken line
that opens with the speaker turned away (its first frame has no face).

This is a word counter on Raphael's English, not a reader of pictures: it errs on the side of the known cases. The
lab (`lab/action_budget/count.py`) holds the corpus and the report to re-tune it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

HARD_MAX = 1
ALL_MAX = 3

_OBJ = r"(?:the |her |his |their |a |an |its |both )?"
# Body parts and non-things: lifting a hand or the eyes is a move; a breath, a sip, steps or a place are not things.
# The look-ahead sits right after the verb, so the regex cannot step around it by leaving "her" out.
_NOT_A_THING = (
    r"(?!(?:(?:the|her|his|their|a|an|its|both) )?"
    r"(?:left |right |quick |running |few |several |small |measured |slow |short |long |brisk )*"
    r"(?:eyes|gaze|head|hands?|chin|face|arms?|brows?|shoulders?|breath|look|steps?|strides?|glance|moment"
    r"|seat|pause|beat|sip|turn|place|cheeks|lips|knees|legs|feet|body|positions?|hold of (?:her|his) (?:nerve|breath))"
    r"\b)"
)
_DOOR = r"(?:car |rear |front |passenger |curbside |curb-side |kerb-side |side )*(?:door|gate|boot)"

# Raphael writes the present tense, third person: "opens", "takes" are verbs; "open box", "outer pocket", "in place"
# are not. "to open" (after "uses her hand to open") is. Each match is one action.
HARD: tuple[tuple[str, str], ...] = (
    # A verb, not a state: "the door swings open", "the door closes"; never "with the door shut".
    ("door", r"\b(?:door|gate|boot|lid|drawer|cupboard)s?\b[^.;,]{0,40}?\b(?:(?:swings|slides|falls|bangs)\s+"
             r"(?:open|shut|closed)|opens|shuts|closes)\b"),
    ("opens/closes", r"\b(?:opens|closes|shuts|slams|unlocks|locks|to open|to close|to shut)\s+" + _OBJ
                     + r"(?:rear |front |car |curb-side |kerb-side |curbside |passenger |side |folded |closed )*"
                       r"(?:door|gate|boot|lid|window|drawer|umbrella|bag|handbag|box|bottle|laptop|book|cupboard"
                       r"|envelope|letter|file)\b"),
    ("door", r"\b(?:pushes|pulls|swings|presses)\s+(?:it|the (?:\w+ ){0,2}door)\s+"
             r"(?:closed|shut|open|outward|outwards)\b"),
    ("umbrella", r"\b(?:umbrella|canopy)\b[^.;]{0,40}?\b(?:opens|closes|folds|unfurls)\b"),
    ("gets out/in", r"\b(?:steps|gets|climbs|slides|rises|emerges)\s+(?:out|into|down from|off|onto the pavement"
                    r"|from the car)\b|\b(?:exits|alights|boards)\b(?!\s+(?:the )?frame)"),
    ("sits/stands", r"\b(?:sits|settles)\s+(?:down|onto|into)\b|\b(?:stands|gets)\s+up\b|\brises\b(?!\s+out)"
                    r"|\b(?:kneels|crouches|lies down)\b"),
    ("takes", r"\b(?:takes|picks\s+up|lifts|grabs|collects|gathers|retrieves|accepts|receives|removes|pulls out)\s+"
              + _NOT_A_THING + _OBJ + r"[\w-]+"),
    ("puts", r"\b(?:moves|lowers) (?:it|the \w+|her \w+|his \w+) (?:\w+ ){0,4}?(?:toward|towards|into|onto|to|in) "
             r"[^.;]{0,30}?(?:pocket|bag|handbag|drawer|box|palm|hand|hands|lap|table|counter)\b"
             r"|\b(?:puts|places (?=it|the|her|his|a |an )|sets\s+down|sets (?:it|the \w+)|tucks|pockets (?:it|the)"
             r"|slips (?:it|the \w+) into|loops|lays (?:it|the)|rests (?:it|the \w+) on|drops (?:it|the \w+) into)\b"
             r"(?!\s+(?:her|his) (?:feet|foot|gaze|eyes|hands?))"),
    ("passes", r"\b(?:hands|passes|gives|offers|throws|tosses)\s+(?:it|him|her|them|the|a|an|his)\b"
               r"(?![^.;]{0,50}\b(?:nod|smile|glance|look|wave|thanks)\b)"),
    ("falls", r"\b(?:drops|falls|slips|tips(?: out| over| outward)|spills|knocks\s+(?:over|off)|tumbles|lands)\b"),
    ("pours/ties", r"\b(?:pours|wraps|unwraps|ties|unties|buttons|zips|plugs|dials)\b"),
    ("dresses", r"\b(?:puts on|takes off|pulls on|slips on|dons)\b"),
    ("vehicle", r"\b(?:car|van|vehicle|driver|three-wheeler|bus|bike|motorbike|tuk)\b[^.;]{0,40}?\b(?:stops|halts"
                r"|pulls up|pulls away|pulls in|parks|brakes|comes to (?:a )?(?:complete )?(?:stop|rest)|drives off"
                r"|moves off|sets off)\b|\bbrings the (?:car|van|vehicle) to (?:a )?(?:stop|rest)\b"),
)
MOVES: tuple[tuple[str, str], ...] = (
    ("walks", r"\b(?:begins|starts) (?:walking|to walk)\b|\bwalks (?:off|away|out|toward|towards|to|past|screen|into"
              r"|along|right|left|rightward|leftward)\b|\bheads (?:off|toward|towards|to|for)\b"
              r"|\bsteps (?:forward|back|aside|toward|towards)\b|\bcrosses\b|\bapproaches\b|\bruns\b|\benters\b"),
    ("turns", r"\bturns\b(?! (?:the|a) (?:page|key|handle))|\bswivels\b|\bpivots\b"),
    ("looks", r"\b(?:looks? (?:up|down|over|across|at|toward|towards|back|away|around|out)|glances?"
              r"|raises (?:her|his) eyes|lifts (?:her|his) (?:eyes|gaze|head)|lowers (?:her|his) (?:eyes|gaze)"
              r"|redirects (?:her|his) (?:eyes|gaze))\b"),
    ("face", r"\b(?:nods|smiles|shakes (?:her|his) head|dips (?:her|his) chin|laughs|frowns|sighs|winces)\b"
             r"|\bgives (?:\w+ ){0,4}?(?:a |an )?(?:[\w-]+ ){0,2}(?:nod|smile|wave|glance)\b"),
    ("body", r"\b(?:leans|reaches|raises|lowers|points|waves|straightens|bends|shifts|stretches)\b"),
)
# One physical event told in several verbs is one action: the rim catches it, it tips, falls and lands = one drop.
_CHAINS = frozenset({"falls"})
# Weather, water, light and tears fall and gather too: no one's action (any hard action, not only a fall).
_NOT_AN_ACTOR = re.compile(r"\b(?:rain|drizzle|droplets?|drops of|an? drop|beads?|raindrops?|water|tears?|light"
                           r"|shadows?|leaves|petals|dusk|night|silence)\b[^.;]{0,25}$")
_STATE = re.compile(r"^\s*(?:\w+\s+){0,3}?(?:continues?|keeps?|remains?|stays?|maintains?|holds?|still|retains?"
                    r"|rests?|sits?|stands?|waits?|listens?|studies|watches|is|are)\b")
_SPLIT = re.compile(r";|\.\s|,\s*(?:then|and then|before|as|while)\s|\s+then\s|,\s+(?=[a-z]+s\b)"
                    r"|\s+and\s+(?=(?:\w+\s+)?[a-z]+s\b)")
# "clears the right edge" is left out: in an insert it is the bag leaving the picture, not a person walking.
TRAVEL = re.compile(r"\b(?:walks|walking|strides?|running|runs|jogs|continues (?:right|left|rightward|leftward"
                    r"|walking|along|on|her walk|his walk)|moves (?:out|off|away|on)\b|heads (?:off|toward|towards|to"
                    r"|for)|exits (?:frame|the frame|right|left)|leaves (?:frame|the frame))")
_OPENED = re.compile(rf"\b(?:already[- ]open|open|opened|ajar)\s+(?:\w+\s+){{0,2}}{_DOOR}\b"
                     rf"|\b{_DOOR}\b[^.;]{{0,30}}?\b(?:opens|swings open|stays open|is open|open)\b"
                     rf"|\b(?:opens|pushes|pulls|swings)\s+(?:the\s+)?(?:\w+\s+){{0,2}}{_DOOR}\s*(?:open|outward)?")
_CLOSED = re.compile(rf"\b(?:closes|shuts|slams)\s+(?:the\s+|it\b)(?:\w+\s+){{0,2}}(?:{_DOOR})?"
                     rf"|\b(?:pushes|presses|pulls|swings)\s+(?:the\s+)?(?:\w+\s+){{0,2}}(?:{_DOOR}|it)\s+(?:shut|closed)\b"
                     rf"|\b{_DOOR}\b[^.;]{{0,30}}?\b(?:closes|shuts|is closed|closed|shut)\b")
_TURNED_AWAY = re.compile(r"\b(?:facing|faces|turned|turns)\s+(?:away|into the (?:vehicle|car|room|bay|stall|wall)"
                          r"|toward the (?:vehicle|wall|interior))\b|\b(?:back|backs) to (?:the )?(?:camera|lens)\b"
                          r"|\bwith (?:his|her|their) back (?:to|toward)\b|\b(?:initially|still) facing into\b")


@dataclass(frozen=True)
class Action:
    kind: str  # hard | move
    label: str
    words: str  # the words matched, as written


@dataclass(frozen=True)
class Count:
    actions: tuple[Action, ...] = ()
    travel: tuple[str, ...] = field(default=())

    @property
    def hard(self) -> list[Action]:
        return [a for a in self.actions if a.kind == "hard"]

    def over(self, hard_max: int = HARD_MAX, all_max: int = ALL_MAX) -> list[str]:
        """Why the clip is over budget; [] when it fits."""
        hard = self.hard
        why = []
        if len(hard) > hard_max:
            why.append(f"{len(hard)} hard actions ({'; '.join(a.words for a in hard)}): give each its own clip, and "
                       "open the next clip on the result (the door already open, the thing already in the hand)")
        if hard and self.travel:
            why.append(f"a hard action ({hard[0].words}) while a person travels ({self.travel[0]}): make the hard "
                       "action its own clip with the person still, and the walk another clip that opens after it")
        if len(self.actions) > all_max:
            why.append(f"{len(self.actions)} actions ({'; '.join(a.words for a in self.actions)}): at most {all_max} "
                       "in one clip")
        return why


def _clause(c: str) -> list[Action]:
    found: list[Action] = []
    taken: list[tuple[int, int]] = []
    for kind, table in (("hard", HARD), ("move", MOVES)):
        for label, pat in table:
            for m in re.finditer(pat, c):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                if kind == "hard" and _NOT_AN_ACTOR.search(c[: m.start()]):
                    continue
                taken.append((m.start(), m.end()))
                found.append(Action(kind, label, m.group(0).strip()))
    if _STATE.match(c) and not any(a.kind == "hard" for a in found):
        return []
    return found


def _same(a: Action) -> str:
    """Two mentions of one action in a clip ("opens the umbrella" / "the umbrella opens") count once; moves never
    merge (two turns are two turns)."""
    if a.kind == "move":
        return ""
    if a.label in _CHAINS:
        return a.label
    label = ("umbrella" if "umbrella" in a.words or "canopy" in a.words
             else "door" if "door" in a.words and a.label in ("opens/closes", "door") else a.label)
    way = "open" if "open" in a.words else "close" if re.search(r"clos|shut", a.words) else ""
    if way:
        return f"{label}|{way}"
    return f"{label}|" + " ".join(w.rstrip("s") for w in re.findall(r"[a-z]+", a.words)[-2:])


def count(beats: Iterable[str]) -> Count:
    """The actions in a clip's beats (each beat's action text, in order)."""
    texts = [b for b in beats if b and b.strip()]
    seen: set[str] = set()
    said: set[str] = set()
    acts: list[Action] = []
    for beat in texts:
        key = re.sub(r"\W+", " ", beat.lower()).strip()
        if key in seen:  # the same beat written twice is one action
            continue
        seen.add(key)
        for c in (x.strip() for x in _SPLIT.split(beat.lower())):
            for a in _clause(c) if c else []:
                same = _same(a)
                if same and same in said:
                    continue
                if same:
                    said.add(same)
                acts.append(a)
    travel = tuple(m.group(0) for b in texts for m in TRAVEL.finditer(b.lower()))
    return Count(tuple(acts), travel)


def door_left_open(clips: Sequence[str]) -> int | None:
    """The index of the first clip (each given as all its words) that opens a door, or has it already open, when no
    clip closes one; None when every opened door is closed."""
    opened = [i for i, text in enumerate(clips) if _OPENED.search(text.lower())]
    if not opened or any(_CLOSED.search(text.lower()) for text in clips):
        return None
    return opened[0]


def turned_away(opening: str) -> str:
    """The words that turn the speaker away in a clip's opening ("facing into the vehicle"); "" when none do."""
    m = _TURNED_AWAY.search(opening.lower())
    return m.group(0) if m else ""


def beats_of(ir: Mapping[str, Any]) -> list[str]:
    """A clip's beat actions, from its IR (`ir.beats[].action`), in order."""
    return [str(b.get("action") or "") for b in ir.get("beats") or [] if isinstance(b, Mapping)]


def opening_of(ir: Mapping[str, Any]) -> str:
    """What a clip opens on, from its IR: the first beat's action, where each subject is, and the first frame's
    subjects. `turned_away` reads it."""
    beats = beats_of(ir)
    frame = ir.get("first_frame") if isinstance(ir.get("first_frame"), Mapping) else {}
    subjects = (frame or {}).get("subjects")
    return " ".join([beats[0] if beats else "",
                     *(str(s.get("position") or "") for s in ir.get("subjects") or [] if isinstance(s, Mapping)),
                     *(str(s) for s in (subjects if isinstance(subjects, list) else [subjects] if subjects else []))])


__all__ = ["ALL_MAX", "HARD_MAX", "Action", "Count", "beats_of", "count", "door_left_open", "opening_of",
           "turned_away"]
