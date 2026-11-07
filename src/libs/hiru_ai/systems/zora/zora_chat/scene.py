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
    stored = stored_of(row)
    if stored is None:
        return ("Zora edits a scene Shot Planner Jonathan has planned. Plan this scene with Jonathan first, or use "
                "the classic director chat.")
    lines = scenes.lines(scene_id)
    canon = scenes.canon(production_id)
    world = World(production=production, scene_row=row, stored=stored,
                  scene=planner_scene(ctx, production_id, row, lines, canon), lines=lines, canon=canon,
                  shot_rows=scenes.shots(scene_id))
    try:
        world.next = next_of(ctx, production_id, row)
    except Exception:  # the seam is a report; a scene list that cannot be read leaves it unchecked
        world.next = Next()
    return world
