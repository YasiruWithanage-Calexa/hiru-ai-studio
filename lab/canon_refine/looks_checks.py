"""Code checks on the looks answer. Report only. Two levels:

- `fix`: wrong on its face (an unknown look, a scene missing, a voice-only person dressed, a condition inside an
  outfit, an id or a blocked word in a description). These go to the repair call.
- `review`: a choice a person should look at (a change of outfit inside continuous story time, one look across a new
  day). Never repaired by the model: listed in the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from checks import ID, REASONING
from contracts import safe_depiction
from looks_schema import LooksAnswer

CONDITION = re.compile(r"\b(wet|soaked|drenched|damp|rain[- ]?(?:darkened|soaked|wet)|muddy|mud|torn|stained|dirty|"
                       r"sweat(?:y|ing)?|dishevel+ed|crumpled|creased|lifeless)\b", re.IGNORECASE)


@dataclass
class Finding:
    id: str  # a scene or look id
    level: str  # fix | review
    message: str


def check(a: LooksAnswer, scene_ids: list[str], truth: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    people = truth["people"]
    looks = {lk.id: lk for lk in a.looks}

    for name, got in (("story", [s.scene for s in a.story]), ("scenes", [s.scene for s in a.scenes])):
        for sid in scene_ids:
            if got.count(sid) != 1:
                out.append(Finding(sid, "fix", f"{sid} appears {got.count(sid)} times in `{name}`"))
        for sid in set(got) - set(scene_ids):
            out.append(Finding(sid, "fix", f"`{name}` names {sid}, which is not a scene"))
    for s in a.story:
        if s.continuous_with and s.continuous_with not in scene_ids:
            out.append(Finding(s.scene, "fix", f"{s.scene} continues {s.continuous_with!r}, which is not a scene"))

    used: set[str] = set()
    for lk in a.looks:
        if lk.person not in people:
            out.append(Finding(lk.id, "fix", f"look {lk.id} is for {lk.person}, who is not a person here"))
        if not lk.id.startswith(f"{lk.person}-"):
            out.append(Finding(lk.id, "fix", f"look id {lk.id} does not start with its person {lk.person}-"))
        worn = " ".join([lk.outfit, lk.hair, lk.makeup, lk.accessories])
        if m := CONDITION.search(worn):
            out.append(Finding(lk.id, "fix", f"look {lk.id} says {m.group(0)!r}: a condition belongs to the scene, "
                                             "the look is the clean, dry outfit"))
        if ids := sorted(set(ID.findall(worn + " " + lk.name))):
            out.append(Finding(lk.id, "fix", f"look {lk.id} writes {', '.join(ids)}; write names"))
        if m := REASONING.search(worn):
            out.append(Finding(lk.id, "fix", f"look {lk.id} says {m.group(0)!r} in what it shows"))
        for f in safe_depiction.blocking(worn):
            out.append(Finding(lk.id, "fix", f"look {lk.id} says {f.said!r}; write {f.instead}"))

    wearing: dict[str, dict[str, str]] = {}  # scene -> person -> look
    for sw in a.scenes:
        seen = [w.person for w in sw.on_screen]
        for p in set(seen):
            if seen.count(p) > 1:
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {p} is listed {seen.count(p)} times"))
        for w in sw.on_screen:
            used.add(w.look)
            lk = looks.get(w.look)
            if lk is None:
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {people.get(w.person, w.person)} wears {w.look}, "
                                                    "which is not a look"))
            elif lk.person != w.person:
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {w.person} wears {w.look}, which is {lk.person}'s"))
            for f in safe_depiction.blocking(w.condition):
                out.append(Finding(sw.scene, "fix", f"{sw.scene} condition says {f.said!r}; write {f.instead}"))
            if ids := sorted(set(ID.findall(w.condition))):
                out.append(Finding(sw.scene, "fix", f"{sw.scene} condition writes {', '.join(ids)}; write names"))
        wearing[sw.scene] = {w.person: w.look for w in sw.on_screen}
        known = (truth.get("on_screen") or {}).get(sw.scene)
        if known is not None:
            for p in sorted(set(known) - set(seen)):
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {people.get(p, p)} is on screen but has no look"))
            for p in sorted(set(seen) - set(known)):
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {people.get(p, p)} is not on screen (voice only "
                                                    "or absent) but is given a look"))
    for lk in a.looks:
        if lk.id not in used:
            out.append(Finding(lk.id, "review", f"look {lk.id} {lk.name!r} is worn in no scene"))

    # continuity: inside continuous time a person keeps the outfit; across a new day one outfit is worth a look
    for s in a.story:
        prev = s.continuous_with
        if not prev or prev not in wearing or s.scene not in wearing:
            continue
        for p, look in wearing[s.scene].items():
            before = wearing[prev].get(p)
            if before and before != look:
                out.append(Finding(s.scene, "review", f"{people.get(p, p)} changes {before} -> {look} between {prev} "
                                                      f"and {s.scene}, which the answer calls continuous"))
    order = sorted(a.story, key=lambda s: (s.story_day, s.scene))
    last: dict[str, tuple[int, str, str]] = {}
    for s in order:
        for p, look in wearing.get(s.scene, {}).items():
            if p in last and last[p][0] != s.story_day and last[p][1] == look:
                out.append(Finding(s.scene, "review", f"{people.get(p, p)} wears {look} on day {last[p][0]} "
                                                      f"({last[p][2]}) and again on day {s.story_day} ({s.scene})"))
            last[p] = (s.story_day, look, s.scene)
    return out
