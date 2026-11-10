"""The scene as Zora reads it (plan/2026-11-06e §3 READ): the stored plan, the scene AS THE PLANNER IS GIVEN IT, and the
scene after it (for the seam).

The planner's own scene builder is reached by id (`core.parts`, ADR 0009), so the blocks, line ids, cast and place the
kernel and the planner's checks see are exactly the ones the planner planned from; nothing of the planner is imported.
This file, `zora_kernel/step.py`, `zora_board/gate.py` and `zora_save/step.py` are the Zora files that name the planner
(`tests/jonathan/test_removal.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from contracts import sceneplan
from hiru_ai.core import parts
from hiru_ai.core.context import RunContext

Row = dict[str, Any]
PLANNER = "jonathan"  # the planner whose stored plan Zora edits
SYSTEM = f"{PLANNER}_shot_planner"


def stored_of(scene: Row | None) -> Row | None:
    """The planner's stored plan on a scene row (`scenes.jonathan`), or None: Zora edits only a scene it planned."""
    raw = (scene or {}).get(PLANNER)
    return raw if isinstance(raw, dict) and raw.get("planner") == PLANNER and isinstance(raw.get("plan"), dict) \
        else None


@dataclass
class Next:
    """The scene after this one, when it carries on from it and the planner has planned it."""

    number: int = 0
    link: str = ""
    start: Row | None = None
    plan: Row | None = None
    label: str = ""


@dataclass
class World:
    production: Row
    scene_row: Row
    stored: Row
    scene: Row  # the planner's scene (`SceneS` as data): numbered blocks, cast, others, place
    lines: list[Row]
    canon: list[Row]
    shot_rows: list[Row]
    next: Next = field(default_factory=Next)


_SIZES = {"EWS", "WIDE", "MWS", "MS", "MCU", "CU", "ECU", "TWO", "OTS", "INSERT", "POV"}
_SIZE_OF = {"WS": "WIDE", "LS": "WIDE", "EXTREME WIDE": "EWS", "MEDIUM": "MS", "CLOSE": "CU"}


def _take(seconds: Any) -> int:
    """A shot's stored length as a take Veo makes (4 / 6 / 8 s)."""
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        s = 0
    return 4 if s <= 4 else 6 if s <= 6 else 8


def _obj(value: Any) -> Row:
    return value if isinstance(value, dict) else {}


def adopt(scene_row: Row, shot_rows: list[Row], lines: list[Row]) -> Row | None:
    """A stored plan in the planner's shape, built from the shots already on a scene another planner (or a person)
    made, so Zora can edit any scene (2026-11-09). Code only, no model: each shot keeps its number, script blocks,
    spoken lines, size, length, link and finished camera design; the treatment is empty (Zora's reply says so when
    asked). Nothing is stored here: the first edit Zora saves writes it. None when the scene has no shots."""
    if not shot_rows:
        return None
    items = sceneplan.scene_items(scene_row, lines)
    short_of = {str(i.line_id): f"L{i.index}" for i in items if i.is_line}  # the planner's short id: L<block>
    n_blocks = len(items)
    rows = sorted(shot_rows, key=lambda r: int(r.get("number") or 0))
    shots = []
    for n, row in enumerate(rows, start=1):
        sid = str(row.get("id"))
        start, end = int(row.get("block_start") or 0), int(row.get("block_end") or 0)
        spoken = [short_of[str(ln["id"])] for ln in lines
                  if str(ln.get("shot_id") or "") == sid and str(ln["id"]) in short_of]
        ir = _obj(row.get("ir"))
        cine = _obj(ir.get("cinematography"))
        card = _obj(row.get("card"))
        sound = _obj(card.get("sound"))
        framing = str(row.get("framing") or "MS").upper()
        size = framing if framing in _SIZES else _SIZE_OF.get(framing, "MS")
        take = _take(row.get("duration_s"))
        link = str(row.get("camera_link") or "cut")
        intent = _obj(row.get("intent"))
        shots.append({
            "n": n, "sequence": "A", "blocks": [b for b in range(start, end) if b < n_blocks], "lines": spoken,
            "over": "", "size": size, "angle": str(cine.get("angle") or "eye level"),
            "lens": str(cine.get("camera") or ""), "take_s": take, "use_s": take,
            "link": link if link in ("cut", "continuous", "match") else "cut",
            "why": str(intent.get("purpose") or row.get("title") or f"Shot {n}"), "ir": dict(ir),
            "sound": {"ambience": str(sound.get("ambience") or ""), "effects": str(sound.get("effects") or ""),
                      "music": str(sound.get("music") or ""), "silence": bool(sound.get("silence"))}})
    plan = {"treatment": {"logline": "", "arc": [], "approach": "", "colour_script": [], "geography": "",
                          "key_image": "", "advice": []},
            "sequences": [{"id": "A", "title": "The scene", "purpose": "",
                           "shots": {"first": 1, "last": len(shots)}}],
            "shots": shots, "added": [], "staging": {"zones": [], "marks": []},
            "end_state": {"people": [], "props": [], "time": "", "light": ""}}
    return {"planner": PLANNER, "plan": plan, "line_ids": {v: k for k, v in short_of.items()},
            "previous": {"planner": str(rows[0].get("planner") or "classic"), "adopted": True}}


def planner_scene(ctx: RunContext, production_id: UUID, scene_row: Row, lines: list[Row], canon: list[Row]) -> Row:
    """The scene's blocks, cast and place exactly as the planner builds them for its author."""
    build = parts.module("system", SYSTEM, "scene")
    split = ctx.need("split")
    characters = split.characters(production_id)
    locations = {str(r["id"]): r for r in split.locations(production_id)}
    props = [c for c in canon if c.get("kind") == "prop"]
    bare, _ = build.script_of(scene_row, lines, cast=[], others=[], place="", objects=[])
    cast = build.present(characters, bare.blocks)
    location = locations.get(str(scene_row.get("location_id")))
    place = str((location or {}).get("name") or scene_row.get("heading") or "")
    script, _ = build.script_of(scene_row, lines, cast=cast, others=build.others_of(characters, cast), place=place,
                                objects=build.objects_of(props, location, bare.blocks))
    return dict(script.model_dump(mode="json"))


def next_of(ctx: RunContext, production_id: UUID, scene_row: Row) -> Next:
    """The next scene of the same episode, when the planner says it carries on from this one."""
    rows = [r for r in ctx.need("scenes").scenes(production_id, None)
            if str(r.get("episode_id")) == str(scene_row.get("episode_id"))]
    rows.sort(key=lambda r: int(r.get("number") or 0))
    ids = [str(r["id"]) for r in rows]
    at = ids.index(str(scene_row["id"])) if str(scene_row["id"]) in ids else -1
    if at < 0 or at + 1 >= len(rows):
        return Next()
    nxt = rows[at + 1]
    kept = stored_of(nxt)
    link = str(((kept or {}).get("link") or {}).get("kind") or "")
    return Next(number=int(nxt.get("number") or 0), link=link, start=(kept or {}).get("start"),
                plan=(kept or {}).get("plan") if kept else None, label=f"Scene {nxt.get('number')}")


def read(ctx: RunContext, production_id: UUID, scene_id: UUID) -> World | str:
    """The world of one turn, or the sentence to say when there is none."""
    scenes, director = ctx.need("scenes"), ctx.need("director")
    production = scenes.production(production_id)
    row = director.scene(production_id, scene_id)
    if production is None or row is None:
        return "This scene is no longer available."
    lines = scenes.lines(scene_id)
    shot_rows = scenes.shots(scene_id)
    stored = stored_of(row) or adopt(row, shot_rows, lines)  # any planner's scene: its shots, as the planner's plan
    if stored is None:
        return "This scene has no shots yet. Plan its shots first, then Zora can edit them."
    canon = scenes.canon(production_id)
    world = World(production=production, scene_row=row, stored=stored,
                  scene=planner_scene(ctx, production_id, row, lines, canon), lines=lines, canon=canon,
                  shot_rows=shot_rows)
    try:
        world.next = next_of(ctx, production_id, row)
    except Exception:  # the seam is a report; a scene list that cannot be read leaves it unchecked
        world.next = Next()
    return world
