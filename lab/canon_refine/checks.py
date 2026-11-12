"""Code checks on the refine answer. Report only: nothing is edited here. Pure.

A finding names the entity id and why, so a repair call can be sent for the failed entries alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from contracts import safe_depiction
from schema import Answer, Value

WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = {"the", "and", "with", "a", "an", "of", "in", "on", "to", "his", "her", "is", "at", "for", "only", "when"}
ID = re.compile(r"\b[CLP]\d{2,3}\b")  # a breakdown id written inside a description
# the model explaining itself inside a value (run1: "weak overcast light avoids fixing an unstated hour"). Not
# "supports": run2's garage had "steel supports", a real building word.
REASONING = re.compile(r"\b(suggests?|avoids?|avoiding|impl(?:y|ies|ied)|because|in order to|unstated|"
                       r"establish(?:es|ed)?|to show|indicates?)\b", re.IGNORECASE)
# a script gender is read from a word like these on its line ("a faded photo of him and Aruni")
GENDERED = {"man": {"he", "him", "his", "himself", "man", "brother", "son", "father", "husband", "boy", "mr"},
            "woman": {"she", "her", "hers", "herself", "woman", "sister", "daughter", "mother", "wife", "girl", "mrs"}}


@dataclass
class Finding:
    id: str
    code: str  # missing | unknown | script | people | parent | safe | gender | duplicate
    message: str


def words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP}


def script_ok(v: Value, lines: list[str]) -> str:
    """'' when a `script` value holds up against the line it names, else why not. An inferred value is not checked."""
    if v.source != "script":
        return ""
    if not 1 <= v.line <= len(lines):
        return f"says script line {v.line}, which does not exist"
    line = lines[v.line - 1].lower()
    digits = re.findall(r"\d+", v.value)
    if digits and not all(d in line for d in digits):
        return f"says {v.value!r} is on line {v.line}, but the line has no {', '.join(digits)}"
    own = words(v.value)
    if own and not digits:
        shared = len(own & words(line)) / len(own)
        if shared < 0.5:
            return f"says {v.value!r} is read from line {v.line}, but most of its words are not on that line"
    return ""


def gender_ok(v: Value, lines: list[str]) -> str:
    """A script gender holds up when its line has a gendered word of that gender (he, him, she, brother...)."""
    if v.source != "script":
        return ""
    if not 1 <= v.line <= len(lines):
        return f"says script line {v.line}, which does not exist"
    said = {"male": "man", "man": "man", "female": "woman", "woman": "woman"}.get(v.value.strip().lower(), "")
    if said and not (GENDERED[said] & set(WORD.findall(lines[v.line - 1].lower()))):
        return f"says {v.value!r} is read from line {v.line}, but that line has no word like {sorted(GENDERED[said])[:4]}"
    return ""


def check(answer: Answer, memory: dict[str, Any], lines: list[str]) -> list[Finding]:
    ents = {e["id"]: e for e in memory["entities"]}
    kinds = {"people": "person", "places": "place", "things": "thing"}
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for group, kind in kinds.items():
        for item in getattr(answer, group):
            seen[item.id] = seen.get(item.id, 0) + 1
            if item.id not in ents:
                out.append(Finding(item.id, "unknown", f"{item.id} is not a breakdown id"))
            elif ents[item.id]["kind"] != kind:
                out.append(Finding(item.id, "unknown", f"{item.id} is a {ents[item.id]['kind']}, answered as a {kind}"))
    for eid, n in seen.items():
        if n > 1:
            out.append(Finding(eid, "duplicate", f"{eid} is answered {n} times"))
    for eid in ents:
        if eid not in seen:
            out.append(Finding(eid, "missing", f"{eid} {ents[eid]['name']} has no answer"))

    # who a place look may not name: every person's name and its words (Nimal, Inspector Ruwan -> ruwan)
    people = {e["name"].lower() for e in ents.values() if e["kind"] == "person"}
    person_words = {w for n in people for w in n.split() if len(w) > 3 and w not in {"inspector"}}

    def values(item: Any) -> list[tuple[str, Value]]:
        return [(k, v) for k, v in item if isinstance(v, Value)]

    for item in [*answer.people, *answer.places, *answer.things]:
        for field, v in values(item):
            why = gender_ok(v, lines) if field == "gender" else script_ok(v, lines)
            if why:
                out.append(Finding(item.id, "script", f"{item.id} {field}: {why}"))
            if ids := sorted(set(ID.findall(v.value))):
                out.append(Finding(item.id, "id", f"{item.id} {field}: writes {', '.join(ids)}; write the names instead"))
            if m := REASONING.search(v.value):
                out.append(Finding(item.id, "reasoning", f"{item.id} {field}: says {m.group(0)!r}, which explains a "
                                   "choice; the value only describes, the reason goes in `reason`"))
            for f in safe_depiction.blocking(v.value):
                out.append(Finding(item.id, "safe", f"{item.id} {field}: says {f.said!r}; write {f.instead}"))
    for p in answer.people:
        if len(p.age.value) > 14 or not re.search(r"\d", p.age.value):  # "30", "late 40s"; never the cast-list sentence
            out.append(Finding(p.id, "script", f"{p.id} age {p.age.value!r} is not a short age"))
        if p.gender.value.strip().lower() not in {"man", "woman", "male", "female"}:
            out.append(Finding(p.id, "gender", f"{p.id} gender {p.gender.value!r} is not man or woman"))
    places = {p.id: p for p in answer.places}
    for p in answer.places:
        look = p.look.value.lower()
        named = sorted(w for w in person_words if re.search(rf"\b{re.escape(w)}\b", look))
        if named:
            out.append(Finding(p.id, "people", f"{p.id} look names {', '.join(named)}: a place look shows no people"))
        if p.kind in ("set", "vehicle") and len(words(look)) < 8:
            out.append(Finding(p.id, "people", f"{p.id} is a {p.kind} but its look is too thin to paint"))
        if p.kind == "spot" and (p.parent not in places or places[p.parent].kind not in ("set", "vehicle")):
            out.append(Finding(p.id, "parent", f"{p.id} is a spot but its parent {p.parent!r} is not a set or vehicle"))
    for lk in answer.looks:
        if lk.person not in ents or ents[lk.person]["kind"] != "person":
            out.append(Finding(lk.person, "unknown", f"look {lk.name!r} is for {lk.person}, which is not a person"))
        text = " ".join([lk.name, lk.outfit, lk.hair, lk.makeup, lk.accessories])
        for f in safe_depiction.blocking(text):
            out.append(Finding(lk.person, "safe", f"look {lk.name!r}: says {f.said!r}; write {f.instead}"))
        if ids := sorted(set(ID.findall(text + " " + lk.why))):
            out.append(Finding(lk.person, "id", f"look {lk.name!r}: writes {', '.join(ids)}; write the names instead"))
        if m := REASONING.search(text):
            out.append(Finding(lk.person, "reasoning", f"look {lk.name!r}: says {m.group(0)!r} in what it shows"))
    return out
