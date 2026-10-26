"""The resolved structure → rows. Pure; the store writes them.

Rebuilding is safe to repeat: episodes and scenes keep their ids (matched by number), an
APPROVED scene is never rewritten, and scenes that no longer exist in the script are removed
unless approved. Places and speakers that are not in the canon yet are added to it as drafts
(a person reviews them in the canon library), so every line has a character and every scene a
location from the start.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from contracts.canon import (
    CanonCard,
    CanonKind,
    name_key,
    next_code,
    reference_sheet_prompt,
    voice_pin,
    wardrobe_anchor,
)
from contracts.timing import words_in

Row = dict[str, Any]


@dataclass
class WritePlan:
    entities: list[tuple[Row, Row]] = field(default_factory=list)
    episodes: list[Row] = field(default_factory=list)
    scenes: list[tuple[Row, list[Row]]] = field(default_factory=list)
    delete_scene_ids: list[str] = field(default_factory=list)
    kept_approved: int = 0
    new_characters: list[str] = field(default_factory=list)

    @property
    def scene_ids(self) -> list[str]:
        return [str(s["id"]) for s, _ in self.scenes]


def _entity(kind: CanonKind, name: str, code: str, production_id: str, actor: str | None,
            aspect_ratio: str, summary: str) -> tuple[Row, Row]:
    entity_id = str(uuid4())
    card = CanonCard(summary=summary)
    character = kind is CanonKind.CHARACTER
    version = {"id": str(uuid4()), "entity_id": entity_id, "production_id": production_id, "version": 1,
               "card": card.model_dump(),
               "card_hash": hashlib.sha256(json.dumps(card.model_dump(), sort_keys=True).encode()).hexdigest(),
               "wardrobe_anchor": wardrobe_anchor(card) if character else "",
               "voice_pin": voice_pin(card) if character else "",
               "reference_prompt": reference_sheet_prompt(kind, name, card, aspect_ratio=aspect_ratio),
               "source": "extract", "created_by": actor}
    return ({"id": entity_id, "production_id": production_id, "kind": kind.value, "code": code,
             "name": name[:120], "aliases": [], "core": False}, version)


def _display(raw: str) -> str:
    raw = " ".join(raw.split())
    return " ".join(w[:1].upper() + w[1:].lower() for w in raw.split()) if raw == raw.upper() else raw


def plan(structure: dict[str, Any], *, production_id: str, canon: list[Row], existing_episodes: list[Row],
         existing_scenes: list[Row], envelope_s: int, aspect_ratio: str, actor: str | None) -> WritePlan:
    out = WritePlan()
    taken = {str(c["code"]) for c in canon}
    known: dict[tuple[str, str], str] = {}
    for c in canon:
        for n in [c["name"], *(c.get("aliases") or [])]:
            known.setdefault((c["kind"], name_key(n)), str(c["id"]))

    def resolve(kind: CanonKind, ref: dict[str, Any] | None, summary: str) -> str | None:
        if not ref:
            return None
        if ref.get("id"):
            return str(ref["id"])
        name = _display(str(ref.get("new") or ""))
        if not name:
            return None
        key = (kind.value, name_key(name))
        if key not in known:
            code = next_code(kind, taken)
            taken.add(code)
            entity, version = _entity(kind, name, code, production_id, actor, aspect_ratio, summary)
            out.entities.append((entity, version))
            known[key] = entity["id"]
            if kind is CanonKind.CHARACTER:
                out.new_characters.append(name)
        return known[key]

    episode_ids = {int(e["number"]): str(e["id"]) for e in existing_episodes}
    scenes_by_key = {(str(s["episode_id"]), int(s["number"])): s for s in existing_scenes}
    for ep in structure["episodes"]:
        episode_id = episode_ids.get(ep["number"]) or str(uuid4())
        out.episodes.append({"id": episode_id, "production_id": production_id, "number": ep["number"],
                             "title": ep["title"][:200], "synopsis": ep["synopsis"][:4000],
                             "status": "building" if ep["scenes"] else "draft",
                             "source_document_ids": ep["doc_ids"]})
        for scene in ep["scenes"]:
            old = scenes_by_key.pop((episode_id, scene["number"]), None)
            if old is not None and old["status"] == "approved":
                out.kept_approved += 1
                continue
            scene_id = str(old["id"]) if old else str(uuid4())
            heading = scene["heading"]
            location_id = resolve(CanonKind.LOCATION, scene.get("location"), f"From the scripts: {heading['raw']}")
            blocks: list[Row] = []
            lines: list[Row] = []
            for block in scene["blocks"]:
                if block["kind"] == "dialogue":
                    line_id = str(uuid4())
                    speaker = block["speaker"]
                    lines.append({"id": line_id, "production_id": production_id, "scene_id": scene_id,
                                  "ord": len(lines), "speaker": _display(speaker),
                                  "character_id": resolve(CanonKind.CHARACTER, block.get("character"),
                                                          f"Speaks in the scripts as {speaker}."),
                                  "text": block["text"], "delivery": block["delivery"],
                                  "words": words_in(block["text"])})
                    blocks.append({"kind": "dialogue", "text": "", "line_id": line_id})
                else:
                    blocks.append({"kind": block["kind"], "text": block["text"], "line_id": None})
            out.scenes.append(({
                "id": scene_id, "production_id": production_id, "episode_id": episode_id,
                "number": scene["number"], "heading": heading["raw"][:300], "title": scene["title"][:120],
                "location_id": location_id, "time_of_day": heading["time_of_day"].lower(),
                "envelope_s": int(old["envelope_s"]) if old else int(scene.get("envelope_s") or envelope_s),
                "script": blocks,
                "script_version": int(old["script_version"]) + 1 if old else 1, "status": "draft",
                "fit_report": {},
            }, lines))
    # Scenes left over in an episode the scripts rebuilt no longer exist in the script.
    rebuilt = {e["id"] for e, src in zip(out.episodes, structure["episodes"], strict=True) if src["scenes"]}
    for (episode_id, _number), old in scenes_by_key.items():
        if episode_id in rebuilt and old["status"] != "approved":
            out.delete_scene_ids.append(str(old["id"]))
    return out
