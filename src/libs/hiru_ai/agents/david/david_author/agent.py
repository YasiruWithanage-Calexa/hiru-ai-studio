"""david_author hooks (plan/2026-11-05e §4.2).

The answer is cleaned entry by entry and nothing else (whether a line is missing, a take too short or a person invented
stays with the checks, which give the author the exact sentence): a shot that names a block or a line the scene lacks
loses that reference, an addition for a shot that is not there goes, and a staging mark for a person who is not in the
scene, a spot the map lacks or a block the scene lacks is dropped. There is no fallback (plan §4.2): with no model the
job fails clearly and names the classic planner.

The shape of a shot's camera design is not Python: it is the clip schema YAML the `serialize` step ships, the one the
DoP
fills, turned into a strict JSON schema at run time. So `output_schema()` returns DavidWire's schema with that design in
place of the free `ir` object.
"""
from __future__ import annotations

from typing import Any

from contracts.david.plan import norm
from contracts.david.wire import DavidWire, renumber
from hiru_ai.agents.david.david_author.schema import Input, Output
from hiru_ai.agents.david.wire_schema import wire_schema

SCHEMA_NAME = "david_plan"


def output_schema() -> dict[str, Any]:
    return wire_schema(DavidWire, SCHEMA_NAME)


def user_message(inp: Input) -> str:
    return inp.pack


def finish(inp: Input, out: Output) -> Output:
    scene = inp.scene
    blocks = {b.index for b in scene.blocks}
    lines = {b.line_id for b in scene.lines}
    cast = {norm(c) for c in scene.cast}
    shots = [s.model_copy(update={"blocks": [b for b in s.blocks if b in blocks],
                                  "lines": [ln for ln in s.lines if ln in lines]}) for s in out.shots]
    numbered = renumber(shots, out.added)
    zones = {z.strip().casefold() for z in out.staging.zones}
    marks = [m for m in out.staging.marks if norm(m.who) in cast and m.block in blocks
             and (m.zone.strip().casefold() in zones or m.zone.strip().casefold() == "off")]
    staging = out.staging.model_copy(update={"marks": marks})
    return Output(notes=out.notes, shots=numbered["shots"], added=numbered["added"], staging=staging,
                  end_state=out.end_state)
