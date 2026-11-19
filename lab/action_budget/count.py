"""Action-budget lab (2026-11-18), step 2: count the actions in every Raphael clip and test a budget.

    python lab/action_budget/count.py [--hard 1] [--moves 3]        free, offline (reads runs/corpus.json)

The budget is per clip and has no seconds in it (the person, 2026-11-18: "action budget for clip not length; length
depends on how long the action takes"). It counts, in Raphael's own beats:
- HARD actions: a change of state the video model has to invent (a door opens or closes, someone gets out of or into
  a vehicle, sits down or stands up, an object is taken, put, passed, dropped or falls, an umbrella opens, clothes go
  on or off, a vehicle stops or pulls away);
- MOVES: a simple visible movement (walks off, turns, looks, nods, smiles, leans, reaches);
- states ("keeps", "remains", "still in her hand", "continues walking") are not actions and are not counted.

A clip is OVER when it has more than --hard hard actions or more than --moves actions in all. Output: runs/report.md
(the numbers, the person's known cases, every over-budget clip with its counted words) and runs/counts.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "runs" / "corpus.json"

# --- what counts --------------------------------------------------------------------------------------------------

_OBJ = r"(?:the |her |his |their |a |an |its |both )?"
# Body parts and non-things: lifting a hand or the eyes is a move, taking a breath or a sip is not handling an object.
# The look-ahead sits right after the verb, so the regex cannot step around it by leaving "her" out.
_NOT_A_THING = (r"(?!(?:(?:the|her|his|their|a|an|its|both) )?(?:left |right |quick |running |few |several |small |measured |slow |short |long |brisk )*"
                r"(?:eyes|gaze|head|hands?|chin|face|arms?|brows?|shoulders?|breath|look|steps?|strides?|glance|moment"
                r"|seat|pause|beat|sip|turn|place|cheeks|lips|knees|legs|feet|body|position|positions|hold of (?:her|his) (?:nerve|breath)|hold of (?:her|his) (?:nerve|breath))\b)")
# Raphael writes the present tense, third person: a verb is "opens", "takes"; "open box", "outer pocket", "in place"
# are not verbs. "to open" (after "uses her hand to open") is.
# Each entry: (label, pattern). Patterns run on lower-cased text; each match is one action.
HARD: list[tuple[str, str]] = [
    ("door opens/closes", r"\b(?:door|gate|boot|lid|drawer|cupboard)s?\b[^.;,]{0,40}?\b(?:swings|slides)?\s*(?:open|opens|shut|shuts|closed|closes)\b"),
    ("opens/closes a thing", r"\b(?:opens|closes|shuts|slams|unlocks|locks|to open|to close|to shut)\s+" + _OBJ + r"(?:rear |front |car |curb-side |kerb-side |passenger |side |folded |closed )*(?:door|gate|boot|lid|window|drawer|umbrella|bag|handbag|box|bottle|laptop|book|cupboard|envelope|letter|file)\b"),
    ("pushes/pulls it closed", r"\b(?:pushes|pulls|swings|presses)\s+(?:it|the (?:\w+ ){0,2}door)\s+(?:closed|shut|open|outward|outwards)\b"),
    ("umbrella opens/closes", r"\b(?:umbrella|canopy)\b[^.;]{0,40}?\b(?:opens|closes|folds|unfurls)\b"),
    ("gets out/in", r"\b(?:steps|gets|climbs|slides|rises|emerges)\s+(?:out|into|down from|off|onto the pavement|from the car)\b|\b(?:exits|alights|boards)\b(?!\s+(?:the )?frame)"),
    ("sits down/stands up", r"\b(?:sits|settles)\s+(?:down|onto|into)\b|\b(?:stands|gets)\s+up\b|\brises\b(?!\s+out)|\b(?:kneels|crouches|lies down)\b"),
    ("takes/picks up", r"\b(?:takes|picks\s+up|lifts|grabs|collects|gathers|retrieves|accepts|receives|removes|pulls out)\s+" + _NOT_A_THING + _OBJ + r"[\w-]+"),
    ("puts/places", r"\b(?:moves|lowers) (?:it|the \w+|her \w+|his \w+) (?:\w+ ){0,4}?(?:toward|towards|into|onto|to|in) [^.;]{0,30}?(?:pocket|bag|handbag|drawer|box|palm|hand|hands|lap|table|counter)\b|\b(?:puts|places (?=it|the|her|his|a |an )|sets\s+down|sets (?:it|the \w+)|tucks|pockets (?:it|the)|slips (?:it|the \w+) into|loops|lays (?:it|the)|rests (?:it|the \w+) on|drops (?:it|the \w+) into)\b(?!\s+(?:her|his) (?:feet|foot|gaze|eyes|hands?))"),
    ("passes/gives", r"\b(?:hands|passes|gives|offers|throws|tosses)\s+(?:it|him|her|them|the|a|an|his)\b(?![^.;]{0,50}\b(?:nod|smile|glance|look|wave|thanks)\b)"),
    ("drops/falls/spills", r"\b(?:drops|falls|slips|tips(?: out| over| outward)|spills|knocks\s+(?:over|off)|tumbles|lands)\b"),
    ("pours/wraps/ties", r"\b(?:pours|wraps|unwraps|ties|unties|buttons|zips|plugs|dials)\b"),
    ("puts on/takes off", r"\b(?:puts on|takes off|pulls on|slips on|dons)\b"),
    ("vehicle stops/starts", r"\b(?:car|van|vehicle|driver|three-wheeler|bus|bike|motorbike|tuk)\b[^.;]{0,40}?\b(?:stops|halts|pulls up|pulls away|pulls in|parks|brakes|comes to (?:a )?(?:complete )?(?:stop|rest)|drives off|moves off|sets off)\b|\bbrings the (?:car|van|vehicle) to (?:a )?(?:stop|rest)\b"),
]
# One physical event told in several verbs is one action: the rim catches it, it tips, falls and lands = one drop.
CHAINS = {"drops/falls/spills"}
# Weather, light and tears fall too; that is no one's action.
NOT_AN_ACTOR = re.compile(r"\b(?:rain|drizzle|droplets?|drops of|beads?|raindrops?|water|tears?|light|shadows?|leaves|petals|dusk|night|silence)\b[^.;]{0,25}$")
MOVES: list[tuple[str, str]] = [
    ("walks off/starts walking", r"\b(?:begins|starts) (?:walking|to walk)\b|\bwalks (?:off|away|out|toward|towards|to|past|screen|into|along|right|left|rightward|leftward)\b|\bheads (?:off|toward|towards|to|for)\b|\bsteps (?:forward|back|aside|toward|towards)\b|\bcrosses\b|\bapproaches\b|\bruns\b|\benters\b"),
    ("turns", r"\bturns\b(?! (?:the|a) (?:page|key|handle))|\bswivels\b|\bpivots\b"),
    ("looks/glances", r"\b(?:looks? (?:up|down|over|across|at|toward|towards|back|away|around|out)|glances?|raises (?:her|his) eyes|lifts (?:her|his) (?:eyes|gaze|head)|lowers (?:her|his) (?:eyes|gaze)|redirects (?:her|his) (?:eyes|gaze))\b"),
    ("nods/smiles/shakes head", r"\b(?:nods|smiles|shakes (?:her|his) head|dips (?:her|his) chin|laughs|frowns|sighs|winces)\b"),
    ("leans/reaches/raises", r"\b(?:leans|reaches|raises|lowers|points|waves|straightens|bends|shifts|stretches)\b"),
]
# A clause that only says something carries on is a state, not an action ("continues walking", "keeps the phone").
STATE = re.compile(r"^\s*(?:\w+\s+){0,3}?(?:continues?|keeps?|remains?|stays?|maintains?|holds?|still|retains?|rests?|sits?|stands?|waits?|listens?|studies|watches|is|are)\b")
SPLIT = re.compile(r";|\.\s|,\s*(?:then|and then|before|as|while)\s|\s+then\s|,\s+(?=[a-z]+s\b)|\s+and\s+(?=(?:\w+\s+)?[a-z]+s\b)")


def clauses(text: str) -> list[str]:
    return [c.strip() for c in SPLIT.split(text.lower()) if c and c.strip()]


def count_clause(c: str) -> list[tuple[str, str, str]]:
    """The actions in one clause: (kind, label, matched words). A pure state clause gives none."""
    found: list[tuple[str, str, str]] = []
    taken: list[tuple[int, int]] = []
    for kind, table in (("hard", HARD), ("move", MOVES)):
        for label, pat in table:
            for m in re.finditer(pat, c):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                if label in CHAINS and NOT_AN_ACTOR.search(c[: m.start()]):
                    continue
                taken.append((m.start(), m.end()))
                found.append((kind, label, m.group(0).strip()))
    if STATE.match(c) and not any(k == "hard" for k, _, _ in found):
        return []
    return found


def beats_of(row: dict[str, Any]) -> list[str]:
    """Raphael's own beats: the clip's ir beats in the lab, the joined `what_we_see` for database shots (their ir.beats
    are the serializer's windows, which repeat a beat)."""
    if row["source"] == "db" and row.get("summary"):
        return [b.strip() for b in row["summary"].split(";") if b.strip()]
    return [b["action"] for b in row["beats"] if b.get("action")]


def _same(kind: str, label: str, words: str) -> str:
    """Two mentions of the same action in one clip ("opens the umbrella" / "the umbrella opens") are one action."""
    if label in CHAINS:
        return label
    if "umbrella" in words or "canopy" in words:
        label = "umbrella opens/closes"
    elif "door" in words and label in ("opens/closes a thing", "door opens/closes", "pushes/pulls it closed"):
        label = "door opens/closes"
    way = "open" if "open" in words else "close" if re.search(r"clos|shut", words) else ""
    if kind == "move":
        return ""  # moves are counted every time: two turns are two turns
    stem = " ".join(w.rstrip("s") for w in re.findall(r"[a-z]+", words)[-2:])
    return f"{label}|{way}|{stem}" if not way else f"{label}|{way}"


def measure(row: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    acts: list[tuple[str, str, str]] = []
    said: set[str] = set()
    for beat in beats_of(row):
        key = re.sub(r"\W+", " ", beat.lower()).strip()
        if key in seen:  # the same beat written twice is one action
            continue
        seen.add(key)
        for c in clauses(beat):
            for kind, label, words in count_clause(c):
                same = _same(kind, label, words)
                if same and same in said:
                    continue
                if same:
                    said.add(same)
                acts.append((kind, label, words))
    hard = [a for a in acts if a[0] == "hard"]
    # Travelling is read on the whole beat, states included: "continues right", "maintains her stride" is still a
    # person crossing the frame while the hard action happens.
    travel = [m.group(0) for b in beats_of(row) for m in TRAVEL.finditer(b.lower())]
    return {"hard": len(hard), "total": len(acts), "acts": acts, "travel": travel}


# A person crossing the frame or walking off. A hard action in the same clip as this is a compound moment (the phone
# slips while she walks on; she gets out and walks off; the umbrella opens mid-walk).
TRAVEL = re.compile(
    r"\b(?:walks|walking|strides?|running|runs|jogs|continues (?:right|left|rightward|leftward|walking|along|on|her walk|his walk)"
    r"|moves (?:out|off|away|on)\b|heads (?:off|toward|towards|to|for)"
    r"|exits (?:frame|the frame|right|left)|leaves (?:frame|the frame))"
    # "clears the right edge" is left out: in an insert it is the bag leaving the picture, not a person walking.
)


def reasons(m: dict[str, Any], hard_max: int, all_max: int) -> list[str]:
    why = []
    if m["hard"] > hard_max:
        why.append(f"{m['hard']} hard actions")
    if m["total"] > all_max:
        why.append(f"{m['total']} actions")
    if m["hard"] and m["travel"]:
        why.append("hard action while travelling")
    return why


# --- the person's known cases ------------------------------------------------------------------------------------

KNOWN = [
    # (production, scene contains, slate, verdict, why)
    ("Love Hour 4", "ANUDI ARRIVES", "2B-1", "bad", "car exit: wrong door, front door, takes failed (2026-11-18)"),
    ("Love Hour 4", "ANUDI ARRIVES", "2C-1", "risky", "umbrella opens mid-walk (umbrella deleted in the phone-drop takes)"),
    ("lab e2e (Api Denna v2)", "E01-S03", "3A-1", "bad", "phone-drop master: walk, tuck, slip, walk on in one clip (five Omni takes)"),
    ("lab coverage (Api Denna v2)", "E01-S03", "3A-1", "good", "coverage insert: the slip alone"),
    ("lab coverage (Api Denna v2)", "E01-S03", "3B-1", "good", "coverage walk-on: phone already on the road"),
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--hard", type=int, default=1, help="hard actions allowed in a clip")
    ap.add_argument("--moves", type=int, default=3, help="actions allowed in a clip in all (hard + moves)")
    a = ap.parse_args()
    rows = json.loads(CORPUS.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for r in rows:
        m = measure(r)
        m["why"] = reasons(m, a.hard, a.moves)
        over = bool(m["why"])
        out.append({**{k: r[k] for k in ("source", "production", "scene", "slate", "stage", "priority", "role",
                                         "size", "take_s")},
                    "beats": beats_of(r), **m, "over": over})
    (HERE / "runs" / "counts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    L: list[str] = [f"# Action budget: hard <= {a.hard}, all actions <= {a.moves} per clip", ""]
    n = len(out)
    over = [o for o in out if o["over"]]
    L += [f"{n} Raphael clips; **{len(over)} over budget ({100 * len(over) / n:.0f} %)**.", ""]
    L += ["| hard actions in a clip | clips |", "|---|---|"]
    for k, v in sorted(Counter(o["hard"] for o in out).items()):
        L.append(f"| {k} | {v} |")
    L += ["", "| actions in all | clips |", "|---|---|"]
    for k, v in sorted(Counter(o["total"] for o in out).items()):
        L.append(f"| {k} | {v} |")
    L += ["", "| production | clips | over |", "|---|---|---|"]
    for p in sorted({o["production"] for o in out}):
        ps = [o for o in out if o["production"] == p]
        L.append(f"| {p} | {len(ps)} | {sum(o['over'] for o in ps)} |")
    L += ["", "| hard action kind | times |", "|---|---|"]
    for k, v in Counter(lbl for o in out for kind, lbl, _ in o["acts"] if kind == "hard").most_common():
        L.append(f"| {k} | {v} |")

    L += ["", "## The person's known cases", "", "| case | verdict | hard | all | budget says |", "|---|---|---|---|---|"]
    for prod, scene, slate, verdict, why in KNOWN:
        hit = [o for o in out if o["production"] == prod and scene in o["scene"] and o["slate"] == slate]
        for o in hit[:1]:
            says = "OVER" if o["over"] else "ok"
            agree = (says == "OVER") == (verdict in ("bad",)) or verdict == "risky"
            L.append(f"| {prod} {slate}: {why} | {verdict} | {o['hard']} | {o['total']} | {says}{'' if agree else ' (DISAGREES)'} |")
        if not hit:
            L.append(f"| {prod} {slate}: {why} | {verdict} | - | - | not found |")

    L += ["", "## Every clip over budget", ""]
    for o in sorted(over, key=lambda o: (-o["hard"], -o["total"])):
        L.append(f"### {o['production']} / {o['scene'][:60]} / {o['slate']} ({o['size']}, {o['take_s']:g} s, "
                 f"stage {o['stage']}): {', '.join(o['why'])}")
        for b in o["beats"]:
            L.append(f"- {b}")
        L.append("- counted: " + "; ".join(f"**{w}**" if k == "hard" else w for k, _, w in o["acts"]))
        L.append("")
    (HERE / "runs" / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
