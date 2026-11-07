"""A production in memory with one scene the planner has planned and stored (the save step's example: the planner's own
write example), for Zora's system, its actions and its API (fakes only, no model, no network)."""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from contracts.director import TurnPayload
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeDirector, FakeRevisions, FakeScenes, FakeSplit
from hiru_ai.steps.zora.zora_save import step as save_step
from tests.zora.world import ROOT

EXAMPLE = ROOT / "src" / "libs" / "hiru_ai" / "steps" / "zora" / "zora_save" / "examples" / "basic.json"
Row = dict[str, Any]


class Director(FakeDirector):
    """The director port reading the scene from the scenes port, so a save is seen by the next read."""

    def __init__(self, scenes: FakeScenes) -> None:
        super().__init__(None)
        self.scenes = scenes

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        return next((dict(r) for r in self.scenes.scene_rows if str(r["id"]) == str(scene_id)
                     and str(r["production_id"]) == str(production_id)), None)


class ChatWorld:
    def __init__(self, *, revisions: bool = True) -> None:
        ex = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.example = ex
        scene = copy.deepcopy(ex["scene"])
        stored = copy.deepcopy(ex["stored"])
        scene["jonathan"] = stored
        self.production, self.scene_id = str(scene["production_id"]), str(scene["id"])
        out = save_step.write_rows(scene, ex["lines"], stored, ex["canon"], ex["production"])
        self.original_ids = [str(r["id"]) for r in out["shots"]]
        scene.update(out["fields"])
        self.scenes = FakeScenes(production={**ex["production"], "id": self.production}, scenes=[scene],
                                 lines=out["lines"], canon=ex["canon"], shots=out["shots"])
        self.split = FakeSplit(characters=[c for c in ex["canon"] if c.get("kind") == "character"],
                               locations=[c for c in ex["canon"] if c.get("kind") == "location"],
                               scenes=self.scenes.scene_rows)
        self.director = Director(self.scenes)
        self.revisions = FakeRevisions(missing=not revisions)
        self.thread = str(uuid4())
        self.user = str(uuid4())

    def ctx(self) -> RunContext:
        ports = replace(Ports(), scenes=self.scenes, split=self.split, director=self.director,
                        revisions=self.revisions)
        return RunContext(production_id=UUID(self.production), actor_user_id=UUID(self.user), ports=ports)

    def payload(self, message: str, *, can_edit: bool = True) -> TurnPayload:
        return TurnPayload(production_id=UUID(self.production), scene_id=UUID(self.scene_id),
                           thread_id=UUID(self.thread), actor_user_id=UUID(self.user), actor_name="Dee",
                           can_edit=can_edit, can_edit_script=True, message=message, user_message_id=uuid4())

    def row(self) -> Row:
        return dict(self.scenes.scene_rows[0])

    def plan(self) -> Row:
        return dict(self.row()["jonathan"]["plan"])

    def shot_ids(self) -> list[str]:
        return [str(r["id"]) for r in self.scenes.shots(self.scene_id)]


def conductor(lane: str, ops: list[Row] | None = None, tasks: list[Row] | None = None, **more: Any) -> Row:
    """A conductor answer in the strict wire shape (every key present)."""
    return {"lane": lane, "confidence": 0.9, "ops": [_flat(o) for o in ops or []], "tasks": tasks or [],
            "variants": more.get("variants", 0), "translate": more.get("translate"), "cannot": more.get("cannot"),
            "memory": more.get("memory", "")}


def author(ops: list[Row] | None = None, notes: str = "", variants: list[Row] | None = None) -> Row:
    return {"notes": notes, "ops": [_flat(o) for o in ops or []], "asks": [],
            "variants": [{"label": v["label"], "ops": [_flat(o) for o in v["ops"]]} for v in variants or []]}


def _flat(op: Row) -> Row:
    from contracts.zora.wire import OP_FIELDS

    return {k: op.get(k) for k in OP_FIELDS}
