"""structure_write: a resolved structure → episodes, scenes and lines (and draft canon for new people and places).

`plan.py` decides (ported from `structure_build/engine/write.py`): episodes and scenes keep their ids, an APPROVED
scene is never rewritten, and scenes that no longer exist in the script are removed unless approved. This applies it
in the builder's order: new canon entities, episodes, each scene with its lines, then the removals.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from hiru_ai.core import tooling
from hiru_ai.core.context import RunContext
from hiru_ai.tools.structure_write.plan import plan


class Args(BaseModel):
    structure: dict[str, Any] = Field(description="The resolved structure: episodes with their scenes and blocks")
    envelope_s: int = Field(description="Seconds a new scene may run", ge=4)
    aspect_ratio: str = "16:9"


class Result(BaseModel):
    entities: int
    episodes: int
    scenes: int
    removed_scenes: int
    kept_approved: int
    new_characters: list[str]
    scene_ids: list[str]


def run(args: Args, ctx: RunContext) -> Result:
    canon = ctx.need("canon", "CanonStore")
    structure = ctx.need("structure", "StructureStore")
    production_id = tooling.production_of(ctx)
    p = plan(args.structure, production_id=str(production_id), canon=canon.entities(production_id),
             existing_episodes=structure.episodes(production_id),
             existing_scenes=structure.scene_headers(production_id), envelope_s=args.envelope_s,
             aspect_ratio=args.aspect_ratio, actor=str(ctx.actor_user_id) if ctx.actor_user_id else None)
    for entity, version in p.entities:
        canon.create_entity(entity, version)
    if p.episodes:
        structure.upsert_episodes(p.episodes)
    for scene, lines in p.scenes:
        structure.write_scene(scene, lines)
    structure.delete_scenes(p.delete_scene_ids)
    return Result(entities=len(p.entities), episodes=len(p.episodes), scenes=len(p.scenes),
                  removed_scenes=len(p.delete_scene_ids), kept_approved=p.kept_approved,
                  new_characters=p.new_characters, scene_ids=p.scene_ids)


def as_tool() -> StructuredTool:
    return tooling.from_part(__package__ or "", Args, run)
