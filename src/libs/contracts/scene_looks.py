"""Scene looks (plan/2026-11-12c §3.1): ONE call decides story time, the looks (one outfit each) and who wears which
look in every scene, with the scene's CONDITION kept apart from the outfit (wet, muddy, lying still), so one look sheet
serves many scenes.

It needs each person's refined appearance and base wardrobe, so it runs after the canon call (`contracts.canon_refine`).
Two inputs, one shape:

- `from_breakdown(bd, refined)`  a production WITH a breakdown: its scenes in page order with their script, who
                                 is on screen (the breakdown's presence: code knows it, so the checks can hold the
                                 answer to it) and its timeline;
- `from_tables(...)`             a production WITHOUT one (D4): today's episodes, scenes and canon cards; the model
                                 reads story time itself and code cannot check presence.

`check` reports `fix` findings (sent to one repair call) and `review` findings (shown to a person). `rows` turns the
answer into draft `canon_looks` (episode ranges from the scenes each look is worn in) and `scene_looks` rows.

Ported from `lab/canon_refine/looks_*.py` (Ekama and You and I 7, 2026-11-12). Pure: no model, no database.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from contracts import safe_depiction
from contracts.breakdown.packet import _pretty
from contracts.breakdown.schema import Breakdown
from contracts.canon_refine import ID, REASONING, Answer, approx_tokens, strict_schema

Row = dict[str, Any]
ON_SCREEN = {"on_screen", "body"}
BUDGET_TOKENS = 40_000
PARTS_OF_DAY = ("dawn", "morning", "day", "evening", "night")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryTime(_M):
    scene: str
    story_day: int
    part_of_day: Literal["dawn", "morning", "day", "evening", "night"]
    continuous_with: str  # a scene id, or ""
    why: str


class Look(_M):
    id: str  # C01-1
    person: str  # C id
    name: str  # "Stall days", "Opening day"
    outfit: str
    hair: str
    makeup: str
    accessories: str
    why: str


class Wear(_M):
    person: str
    look: str
    condition: str
    why: str


class SceneWear(_M):
    scene: str
    on_screen: list[Wear]


class LooksAnswer(_M):
    story: list[StoryTime]
    looks: list[Look]
    scenes: list[SceneWear]


def json_schema() -> dict[str, Any]:
    return strict_schema(LooksAnswer)


# ── the input ────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Truth:
    """What code knows for the checks: the people (id -> name), who is on screen in each scene (None without a
    breakdown) and each scene's episode (for the looks' episode ranges)."""

    people: dict[str, str]
    on_screen: dict[str, list[str]] | None
    episode_of: dict[str, int]


def named(text: str, names: dict[str, str]) -> str:
    """The breakdown's prose writes ids ("C03 reveals evidence concerning C04"): give the model names instead."""
    return re.sub(r"\b[CLP]\d{2,3}\b", lambda m: names.get(m.group(0), m.group(0)), text)


def from_breakdown(bd: Breakdown, refined: Answer) -> tuple[Row, Truth]:
    names = {e.id: _pretty(e.name) for e in bd.entities}
    cards = {p.id: p for p in refined.people}
    people = [
        {
            "id": e.id,
            "name": names[e.id],
            "appearance": cards[e.id].appearance.value if e.id in cards else "",
            "base_wardrobe": cards[e.id].wardrobe.value if e.id in cards else "",
        }
        for e in bd.entities
        if e.kind == "person"
    ]
    scenes, truth, episodes = [], {}, {}
    for sc in bd.scenes:
        b = sc.brief or {}
        script = []
        for blk in sc.blocks:
            if blk.get("kind") == "dialogue" and blk.get("speaker"):
                presence = blk.get("presence", "on_screen") or "on_screen"
                how = "" if presence in ON_SCREEN else f" ({presence.replace('_', ' ')})"
                script.append(f"{names.get(blk['speaker'], blk['speaker'])}{how}: {blk.get('text', '')}")
            elif blk.get("text"):
                script.append(str(blk["text"]))
        present = [
            {"person": f"{p.get('person')} {names.get(str(p.get('person')), '')}", "presence": p.get("presence")}
            for p in b.get("people", [])
        ]
        scenes.append(
            {
                "id": sc.id,
                "episode": sc.episode,
                "heading": sc.heading,
                "place": names.get(str(b.get("place") or ""), ""),
                "people": present,
                "script": script,
            }
        )
        truth[sc.id] = sorted(str(p.get("person")) for p in b.get("people", []) if p.get("presence") in ON_SCREEN)
        episodes[sc.id] = sc.episode
    cont = bd.continuity or {}
    timeline = [
        {k: t.get(k) for k in ("scene", "story_order", "story_day", "relative", "kind", "anchor")}
        for t in cont.get("timeline", [])
    ]
    synopses = [
        {"episode": s.get("episode"), "text": named(str(s.get("text") or ""), names)} for s in cont.get("synopses", [])
    ]
    return (
        {"episodes": synopses, "people": people, "scenes": scenes, "timeline": timeline},
        Truth(people={p["id"]: p["name"] for p in people}, on_screen=truth, episode_of=episodes),
    )


def scene_key(episode: int, number: int) -> str:
    return f"E{episode:02d}-S{number:02d}"


def from_tables(
    episodes: list[Row], scenes: list[Row], lines: dict[str, list[Row]], people: list[Row]
) -> tuple[Row, Truth]:
    """A production without a breakdown (D4). `scenes`: rows with `key` (E01-S02), `episode`, `heading`, `title`,
    `place`, `script` (blocks); `lines`: scene key -> its dialogue rows; `people`: canon characters with their card."""
    ppl = [
        {
            "id": p["code"],
            "name": p["name"],
            "appearance": (p.get("card") or {}).get("appearance", ""),
            "base_wardrobe": (p.get("card") or {}).get("wardrobe", ""),
            "notes": (p.get("card") or {}).get("notes", ""),
        }
        for p in people
    ]
    out_scenes, episode_of = [], {}
    for s in scenes:
        by_id = {str(ln["id"]): ln for ln in lines.get(s["key"], [])}
        text = []
        for b in s.get("script") or []:
            if b.get("kind") == "dialogue" and str(b.get("line_id")) in by_id:
                ln = by_id[str(b["line_id"])]
                text.append(f"{ln.get('speaker')}: {ln.get('text')}")
            elif b.get("text"):
                text.append(str(b["text"]))
        out_scenes.append(
            {
                "id": s["key"],
                "episode": s["episode"],
                "heading": s.get("heading", ""),
                "title": s.get("title", ""),
                "place": s.get("place") or "",
                "script": text,
            }
        )
        episode_of[s["key"]] = int(s["episode"])
    eps = [{"episode": e["number"], "title": e.get("title", ""), "text": e.get("synopsis", "")} for e in episodes]
    return (
        {"episodes": eps, "people": ppl, "scenes": out_scenes, "timeline": None},
        Truth(people={p["id"]: p["name"] for p in ppl}, on_screen=None, episode_of=episode_of),
    )


def message(data: Row, carried: list[Look] | None = None) -> str:
    out = "THE PRODUCTION (JSON)\n" + json.dumps(data, ensure_ascii=False, indent=1)
    if carried:
        out += (
            "\n\nLOOKS ALREADY DECIDED FOR THE EPISODES BEFORE THESE (reuse a look by its id where the story carries "
            "on; make a new one only for a reason)\n"
            + json.dumps([lk.model_dump() for lk in carried], ensure_ascii=False, indent=1)
        )
    return out


def parts(data: Row, budget: int = BUDGET_TOKENS) -> list[Row]:
    """The data in as few calls as fit the budget: all at once, else one episode (or a run of episodes) a call. Each
    part keeps the people; the timeline and synopses are cut to its scenes and episodes."""
    if approx_tokens(message(data)) <= budget:
        return [data]
    order: list[int] = []
    for s in data["scenes"]:
        if s["episode"] not in order:
            order.append(s["episode"])
    groups: list[list[int]] = []
    for ep in order:
        trial = [*groups[-1], ep] if groups else [ep]
        if groups and approx_tokens(message(_part(data, trial))) <= budget:
            groups[-1] = trial
        else:
            groups.append([ep])
    return [_part(data, g) for g in groups]


def _part(data: Row, episodes: list[int]) -> Row:
    scenes = [s for s in data["scenes"] if s["episode"] in episodes]
    ids = {s["id"] for s in scenes}
    return {
        "episodes": [e for e in data["episodes"] if e.get("episode") in episodes],
        "people": data["people"],
        "scenes": scenes,
        "timeline": [t for t in data["timeline"] if t.get("scene") in ids]
        if data.get("timeline") is not None
        else None,
    }


# ── checks ───────────────────────────────────────────────────────────────────────────────────────────────────────────

CONDITION = re.compile(
    r"\b(wet|soaked|drenched|damp|rain[- ]?(?:darkened|soaked|wet)|muddy|mud|torn|stained|dirty|"
    r"sweat(?:y|ing)?|dishevel+ed|crumpled|creased|lifeless)\b",
    re.IGNORECASE,
)


@dataclass
class Finding:
    id: str  # a scene or look id
    level: str  # fix | review
    message: str


def check(a: LooksAnswer, scene_ids: list[str], truth: Truth, carried: list[Look] | None = None) -> list[Finding]:
    """`fix`: wrong on its face (sent to the repair call). `review`: a choice a person should look at."""
    out: list[Finding] = []
    people = truth.people
    looks = {lk.id: lk for lk in [*(carried or []), *a.looks]}

    for name, got in (("story", [s.scene for s in a.story]), ("scenes", [s.scene for s in a.scenes])):
        for sid in scene_ids:
            if got.count(sid) != 1:
                out.append(Finding(sid, "fix", f"{sid} appears {got.count(sid)} times in `{name}`"))
        for sid in sorted(set(got) - set(scene_ids)):
            out.append(Finding(sid, "fix", f"`{name}` names {sid}, which is not a scene"))
    known_scenes = set(scene_ids) | set(truth.episode_of)
    for s in a.story:
        if s.continuous_with and s.continuous_with not in known_scenes:
            out.append(Finding(s.scene, "fix", f"{s.scene} continues {s.continuous_with!r}, which is not a scene"))

    used: set[str] = set()
    for lk in a.looks:
        if lk.person not in people:
            out.append(Finding(lk.id, "fix", f"look {lk.id} is for {lk.person}, who is not a person here"))
        if not lk.id.startswith(f"{lk.person}-"):
            out.append(Finding(lk.id, "fix", f"look id {lk.id} does not start with its person {lk.person}-"))
        worn = " ".join([lk.outfit, lk.hair, lk.makeup, lk.accessories])
        if m := CONDITION.search(worn):
            out.append(
                Finding(
                    lk.id,
                    "fix",
                    f"look {lk.id} says {m.group(0)!r}: a condition belongs to the scene, the look "
                    "is the clean, dry outfit",
                )
            )
        if ids := sorted(set(ID.findall(worn + " " + lk.name))):
            out.append(Finding(lk.id, "fix", f"look {lk.id} writes {', '.join(ids)}; write names"))
        if m := REASONING.search(worn):
            out.append(Finding(lk.id, "fix", f"look {lk.id} says {m.group(0)!r} in what it shows"))
        for f in safe_depiction.blocking(worn + " " + lk.name):
            out.append(Finding(lk.id, "fix", f"look {lk.id} says {f.said!r}; write {f.instead}"))

    wearing: dict[str, dict[str, str]] = {}  # scene -> person -> look
    for sw in a.scenes:
        seen = [w.person for w in sw.on_screen]
        for p in sorted(set(seen)):
            if seen.count(p) > 1:
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {p} is listed {seen.count(p)} times"))
        for w in sw.on_screen:
            used.add(w.look)
            chosen = looks.get(w.look)
            if chosen is None:
                out.append(
                    Finding(
                        sw.scene,
                        "fix",
                        f"{sw.scene}: {people.get(w.person, w.person)} wears {w.look}, which is not a look",
                    )
                )
            elif chosen.person != w.person:
                out.append(
                    Finding(sw.scene, "fix", f"{sw.scene}: {w.person} wears {w.look}, which is {chosen.person}'s")
                )
            for f in safe_depiction.blocking(w.condition):
                out.append(Finding(sw.scene, "fix", f"{sw.scene} condition says {f.said!r}; write {f.instead}"))
            if ids := sorted(set(ID.findall(w.condition))):
                out.append(Finding(sw.scene, "fix", f"{sw.scene} condition writes {', '.join(ids)}; write names"))
        wearing[sw.scene] = {w.person: w.look for w in sw.on_screen}
        known = (truth.on_screen or {}).get(sw.scene) if truth.on_screen is not None else None
        if known is not None:
            for p in sorted(set(known) - set(seen)):
                out.append(Finding(sw.scene, "fix", f"{sw.scene}: {people.get(p, p)} is on screen but has no look"))
            for p in sorted(set(seen) - set(known)):
                out.append(
                    Finding(
                        sw.scene,
                        "fix",
                        f"{sw.scene}: {people.get(p, p)} is not on screen (voice only or absent) but is given a look",
                    )
                )
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
                out.append(
                    Finding(
                        s.scene,
                        "review",
                        f"{people.get(p, p)} changes {before} -> {look} between {prev} "
                        f"and {s.scene}, which the answer calls continuous",
                    )
                )
    order = sorted(a.story, key=lambda s: (s.story_day, PARTS_OF_DAY.index(s.part_of_day), s.scene))
    last: dict[str, tuple[int, str, str]] = {}
    for s in order:
        for p, look in wearing.get(s.scene, {}).items():
            if p in last and last[p][0] != s.story_day and last[p][1] == look:
                out.append(
                    Finding(
                        s.scene,
                        "review",
                        f"{people.get(p, p)} wears {look} on day {last[p][0]} "
                        f"({last[p][2]}) and again on day {s.story_day} ({s.scene})",
                    )
                )
            last[p] = (s.story_day, look, s.scene)
    return out


def repair_message(user: str, answer: LooksAnswer, fixes: list[Finding]) -> str:
    return (
        f"{user}\n\nYOUR EARLIER ANSWER\n{answer.model_dump_json(indent=1)}\n\nTHE CHECKS SAID\n"
        + "\n".join(f"- {f.message}" for f in fixes)
        + "\n\nAnswer again in full, fixing exactly what the checks say and keeping everything else the same."
    )


def join(answers: list[LooksAnswer]) -> LooksAnswer:
    """The answers of a split call as one: a look a later part reuses is kept once."""
    looks: dict[str, Look] = {}
    story: list[StoryTime] = []
    scenes: list[SceneWear] = []
    for a in answers:
        for lk in a.looks:
            looks.setdefault(lk.id, lk)
        story += a.story
        scenes += a.scenes
    return LooksAnswer(story=story, looks=list(looks.values()), scenes=scenes)


# ── the answer as rows (draft looks and scene looks, for `canon_refine_apply`) ───────────────────────────────────────


def ranges(episodes: list[int]) -> list[Row]:
    """[1, 2, 3, 5] -> [{from 1, to 3}, {from 5, to 5}] (an episode 0, a document without episodes, is episode 1)."""
    out: list[Row] = []
    for ep in sorted({max(1, e) for e in episodes}):
        if out and out[-1]["to"] == ep - 1:
            out[-1]["to"] = ep
        else:
            out.append({"from": ep, "to": ep})
    return out[:12]


def rows(
    a: LooksAnswer, truth: Truth, entity_of: dict[str, str], scene_row_of: dict[str, str]
) -> tuple[list[Row], list[Row]]:
    """(looks, scene looks) for the apply. `entity_of`: person id -> canon entity id; `scene_row_of`: scene id ->
    `scenes` row id. A look worn in no scene is still kept as a draft (with the first episode), so a person sees it.
    Names are unique per person (the table's rule): a second "Work days" becomes "Work days (2)"."""
    worn: dict[str, list[int]] = {}
    for sw in a.scenes:
        for w in sw.on_screen:
            worn.setdefault(w.look, []).append(truth.episode_of.get(sw.scene, 1))
    first = min(truth.episode_of.values(), default=1)
    look_rows: list[Row] = []
    names: dict[str, set[str]] = {}
    key_of: dict[str, str] = {}
    for lk in a.looks:
        entity = entity_of.get(lk.person)
        if entity is None:
            continue
        taken = names.setdefault(entity, set())
        name, n = " ".join(lk.name.split())[:110] or lk.id, 2
        base = name
        while name.lower() in taken:
            name, n = f"{base} ({n})", n + 1
        taken.add(name.lower())
        key_of[lk.id] = name
        look_rows.append(
            {
                "entity_id": entity,
                "name": name,
                "ranges": ranges(worn.get(lk.id) or [first]),
                "outfit": lk.outfit[:600],
                "hair": lk.hair[:300],
                "makeup": lk.makeup[:300],
                "accessories": lk.accessories[:600],
            }
        )
    scene_rows: list[Row] = []
    for sw in a.scenes:
        scene = scene_row_of.get(sw.scene)
        if not scene:
            continue
        for w in sw.on_screen:
            entity = entity_of.get(w.person)
            if entity is None or w.look not in key_of:
                continue
            scene_rows.append(
                {
                    "scene_id": scene,
                    "entity_id": entity,
                    "look_name": key_of[w.look],
                    "condition": w.condition[:300],
                    "why": w.why[:300],
                }
            )
    return look_rows, scene_rows
