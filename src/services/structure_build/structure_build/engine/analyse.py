"""Documents + canon → a structure plan, and the questions only a person can answer.

Pure functions over plain dicts (the plan travels through the LangGraph state and its
checkpoints). Nothing here guesses silently where a wrong guess would cost a person work later:

  episode:<doc>     a script that never says which episode it is
  dup:<n>           two scripts that both claim episode n
  loc:<name>        a scene heading's place that only partly matches a canon location
  noloc:<scene>     a scene heading with no place at all
  spk:<name>        a speaker whose name is close to, but not, a canon character

Every question has a suggested answer (its first option). Without a durable checkpointer the
build takes it and records the question as `defaulted`, so nothing blocks and nothing is hidden.
Keys are stable across builds, so an answer a person gave once is reused by every later build.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from contracts.canon import CanonKind, name_key
from contracts.screenplay import ParsedDocument, parse_document, parse_outline

Plan = dict[str, Any]
Question = dict[str, Any]

NEW = "new"
NONE = "none"


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if len(t) > 1 and t not in {"the", "s", "of"}}


def _keys(entity: dict[str, Any]) -> set[str]:
    return {name_key(entity["name"]), *(name_key(a) for a in entity.get("aliases") or [])} - {""}


def match_location(place: str, locations: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """→ (sure match, partial candidate). A sure match is an exact name/alias or one name's words
    containing the other's; a partial candidate shares some words and needs a person."""
    key = name_key(place)
    best, best_score = None, 0.0
    for loc in locations:
        for k in _keys(loc):
            if k == key:
                return loc, None
            a, b = _tokens(key), _tokens(k)
            if a and b and (a <= b or b <= a):
                return loc, None
            score = len(a & b) / max(len(a | b), 1)
            if score > best_score:
                best, best_score = loc, score
    return None, (best if best_score > 0 else None)


Match = tuple[dict[str, Any] | None, dict[str, Any] | None]


def match_speaker(speaker: str, characters: list[dict[str, Any]]) -> Match:
    key = name_key(speaker)
    for c in characters:
        if key in _keys(c):
            return c, None
    for c in characters:
        for k in _keys(c):
            a, b = _tokens(key), _tokens(k)
            if (a and b and a & b) or (len(key) >= 3 and len(k) >= 3 and (k.startswith(key) or key.startswith(k))):
                return None, c
    return None, None


def _q(key: str, scope: str, title: str, body: str, options: list[tuple[str, str]], *, allow_text: bool = False,
       agent: str = "script_architect") -> Question:
    return {"key": key, "scope": scope, "title": title, "body": body, "agent": agent, "allow_text": allow_text,
            "options": [{"value": v, "label": lbl} for v, lbl in options]}


def _scene_title(heading: dict[str, Any]) -> str:
    place = heading["location"].title() if heading["location"].isupper() else heading["location"]
    parts = [p for p in [place, heading["sub_location"].lower(), heading["time_of_day"].lower()] if p]
    return ", ".join(parts)[:120]


def analyse(documents: list[dict[str, Any]], canon: list[dict[str, Any]]) -> Plan:
    """documents: [{id, filename, role, text}] oldest first; canon: [{id, kind, code, name, aliases}]."""
    characters = [c for c in canon if c["kind"] == CanonKind.CHARACTER]
    locations = [c for c in canon if c["kind"] == CanonKind.LOCATION]
    known = {n for c in characters for n in [c["name"], *(c.get("aliases") or [])]}

    outline: dict[int, dict[str, str]] = {}
    for d in documents:
        if d["role"] == "outline":
            for e in parse_outline(d["text"]):
                outline.setdefault(e.number, {"title": e.title, "synopsis": e.synopsis})

    parsed: list[tuple[dict[str, Any], ParsedDocument]] = [
        (d, parse_document(d["text"], d["filename"], known)) for d in documents if d["role"] == "script"]

    questions: list[Question] = []
    claims: dict[int, list[str]] = {}  # episode number → script units claiming it, oldest first
    units: dict[str, dict[str, Any]] = {}  # one parsed episode of one document
    for d, doc in parsed:
        for i, ep in enumerate(doc.episodes):
            if not ep.scenes:
                continue
            uid = f"{d['id']}:{i}"
            scenes = [_scene(s, n) for n, s in enumerate(ep.scenes, start=1)]
            # Lengths the episode's own text stated (prose episodes), one per scene.
            seconds = (d.get("scene_seconds") or {}).get(str(ep.number)) or []
            if len(seconds) == len(scenes):
                for scene, length in zip(scenes, seconds, strict=True):
                    scene["envelope_s"] = int(length)
            units[uid] = {"uid": uid, "doc_id": d["id"], "filename": d["filename"], "number": ep.number,
                          "title": ep.title, "scenes": scenes}
            if ep.number is not None:
                claims.setdefault(ep.number, []).append(uid)

    taken = set(claims) | set(outline)
    for uid, unit in units.items():
        if unit["number"] is None:
            free = [n for n in range(1, 1000) if n not in taken][:3]
            unit["question"] = f"episode:{uid}"
            questions.append(_q(f"episode:{uid}", unit["filename"], "Question · which episode?",
                                f"{unit['filename']} does not say which episode it is.",
                                [(str(n), f"Episode {n}") for n in free], allow_text=True))
    for n, uids in claims.items():
        if len(uids) > 1:
            latest = uids[-1]  # the newest upload is the suggested current draft
            questions.append(_q(f"dup:{n}", f"Ep {n:02d}", f"Question · Ep {n:02d} has {len(uids)} scripts",
                                "More than one script says it is this episode. Which one is current?",
                                [(u, units[u]["filename"]) for u in [latest, *[x for x in uids if x != latest]]]))

    asked_places: set[str] = set()
    asked_speakers: set[str] = set()
    for unit in units.values():
        previous: dict[str, Any] | None = None
        for scene in unit["scenes"]:
            scope = f"{unit['filename']} Scene {scene['number']}"
            place = scene["heading"]["location"]
            if place:
                sure, partial = match_location(place, locations)
                if sure:
                    scene["location"] = {"id": sure["id"], "code": sure["code"]}
                elif partial:
                    qkey = f"loc:{name_key(place)}"
                    scene["location"] = {"question": qkey, "name": place}
                    if qkey not in asked_places:
                        asked_places.add(qkey)
                        questions.append(_q(qkey, scope, f"Question · {scope}",
                                            f"The script's place \"{place}\" is close to {partial['code']} "
                                            f"{partial['name']}. Is it the same place?",
                                            [(partial["code"], f"Use {partial['code']}"), (NEW, "A new location")],
                                            allow_text=True))
                else:
                    scene["location"] = {"new": place}
            elif previous and previous.get("location"):
                qkey = f"noloc:{unit['uid']}:{scene['number']}"
                scene["location"] = {"question": qkey}
                prev = previous["location"]
                label = prev.get("code") or prev.get("new") or prev.get("name") or "the previous place"
                questions.append(_q(qkey, scope, f"Question · {scope}",
                                    f"The script gives no location. Use {label}, as in the scene before?",
                                    [("previous", f"Use {label}"), (NONE, "No fixed location")]))
                scene["location"]["previous"] = prev
            else:
                scene["location"] = None
            for line in [b for b in scene["blocks"] if b["kind"] == "dialogue"]:
                sure_c, partial_c = match_speaker(line["speaker"], characters)
                if sure_c:
                    line["character"] = {"id": sure_c["id"]}
                elif partial_c:
                    qkey = f"spk:{name_key(line['speaker'])}"
                    line["character"] = {"question": qkey, "name": line["speaker"]}
                    if qkey not in asked_speakers:
                        asked_speakers.add(qkey)
                        questions.append(_q(qkey, scope, f"Question · {scope}",
                                            f"Is \"{line['speaker']}\" the same person as {partial_c['code']} "
                                            f"{partial_c['name']}?",
                                            [(partial_c["code"], f"Yes, {partial_c['code']}"),
                                             (NEW, "No, a new character")]))
                else:
                    line["character"] = {"new": line["speaker"]}
            previous = scene
    return {"units": units, "claims": {str(k): v for k, v in claims.items()},
            "outline": {str(k): v for k, v in outline.items()}, "questions": questions}


def _scene(s: Any, number: int) -> dict[str, Any]:
    h = s.heading
    heading = {"raw": h.raw, "int_ext": h.int_ext, "location": h.location, "sub_location": h.sub_location,
               "time_of_day": h.time_of_day}
    return {"number": number, "heading": heading, "title": _scene_title(heading),
            "blocks": [{"kind": b.kind, "text": b.text, "speaker": b.speaker, "delivery": b.delivery}
                       for b in s.blocks]}


def default_answers(questions: list[Question]) -> dict[str, dict[str, Any]]:
    return {q["key"]: {"value": q["options"][0]["value"], "text": None} for q in questions if q["options"]}


_DIGITS = re.compile(r"\d{1,3}")


def apply_answers(plan: Plan, answers: dict[str, dict[str, Any]], canon: list[dict[str, Any]]) -> Plan:
    """The plan with every question resolved → episodes ready to write."""
    by_code = {c["code"]: c for c in canon}
    units = plan["units"]
    claims = {int(k): list(v) for k, v in plan["claims"].items()}
    for uid, unit in units.items():
        key = unit.get("question")
        if key:
            ans = answers.get(key) or {}
            m = _DIGITS.search(str(ans.get("value") or ans.get("text") or ""))
            unit["number"] = int(m.group(0)) if m and int(m.group(0)) >= 1 else None
            if unit["number"] is not None:
                claims.setdefault(unit["number"], []).append(uid)
    chosen: dict[int, str] = {}
    for n, uids in claims.items():
        pick = str((answers.get(f"dup:{n}") or {}).get("value") or "") if len(uids) > 1 else ""
        chosen[n] = pick if pick in uids else uids[-1]

    def resolve_place(loc: dict[str, Any] | None) -> dict[str, Any] | None:
        if not loc:
            return None
        if "question" in loc:
            ans = answers.get(loc["question"]) or {}
            value, text = ans.get("value"), (ans.get("text") or "").strip()
            if loc["question"].startswith("noloc:"):
                return resolve_place(loc.get("previous")) if value == "previous" else None
            if value in by_code:
                return {"id": by_code[value]["id"], "code": value}
            if text:
                sure, _ = match_location(text, [c for c in canon if c["kind"] == CanonKind.LOCATION])
                return {"id": sure["id"], "code": sure["code"]} if sure else {"new": text}
            return {"new": loc.get("name", "")}
        return loc

    episodes: dict[int, dict[str, Any]] = {}
    for n, uid in chosen.items():
        unit = units[uid]
        outline = plan["outline"].get(str(n), {})
        scenes = []
        for scene in unit["scenes"]:
            scene = copy.deepcopy(scene)
            scene["location"] = resolve_place(scene.get("location"))
            for block in scene["blocks"]:
                ch = block.get("character")
                if ch and "question" in ch:
                    value = (answers.get(ch["question"]) or {}).get("value")
                    block["character"] = {"id": by_code[value]["id"]} if value in by_code else {"new": ch["name"]}
            scenes.append(scene)
        episodes[n] = {"number": n, "title": unit["title"] or outline.get("title", ""),
                       "synopsis": outline.get("synopsis", ""), "doc_ids": [unit["doc_id"]], "scenes": scenes}
    for key, ep in plan["outline"].items():
        n = int(key)
        if n not in episodes:
            episodes[n] = {"number": n, "title": ep.get("title", ""), "synopsis": ep.get("synopsis", ""),
                           "doc_ids": [], "scenes": []}
    return {"episodes": [episodes[n] for n in sorted(episodes)]}
