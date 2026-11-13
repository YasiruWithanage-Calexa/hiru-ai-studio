"""The lab's scene as a fixture (plan/2026-11-13 §4): Hiru Short Combined 2, Scene 03, planned by Raphael (20
overlapping clips, L2 / L3 / L4 performed by S05 / S08 / S11). Read from the lab's own copy, never from the database.

`RowsWorld` is a production in memory around it (scenes, director, revisions: fakes only, no network) and `Recorded` the
models' recorded answers (lab run 6), handed to the turn by role in place of a model."""
from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from contracts.coverage.scene import Coverage
from contracts.director import TurnPayload
from contracts.zora.events import ZoraAction, ZoraActionResult
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeDirector, FakeRevisions, FakeScenes
from hiru_ai.systems.zora.zora_chat import graph

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "lab" / "zora_rows"
SCENE_FILE = LAB / "input" / "0f4ba0fd-db0b-4722-8feb-e89586b06f24.json"
RUN6 = LAB / "runs" / "run6" / "turns.json"
Row = dict[str, Any]


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return dict(json.loads(SCENE_FILE.read_text(encoding="utf-8")))


def data() -> dict[str, Any]:
    """The exported rows: production, scene, shots, lines, characters (a fresh copy)."""
    return copy.deepcopy(_data())


def scene() -> Coverage:
    d = data()
    return Coverage.from_rows(d["scene"], d["shots"], d["lines"], d["characters"])


def run6() -> list[dict[str, Any]]:
    return list(json.loads(RUN6.read_text(encoding="utf-8")))


class Director(FakeDirector):
    """The director port reading the scene from the scenes port; a message it stores is in the thread."""

    def __init__(self, scenes: FakeScenes) -> None:
        super().__init__(None)
        self.scenes = scenes

    def scene(self, production_id: UUID, scene_id: UUID) -> Row | None:
        return next((dict(r) for r in self.scenes.scene_rows if str(r["id"]) == str(scene_id)
                     and str(r["production_id"]) == str(production_id)), None)

    def add_message(self, row: Row) -> None:
        self.history.append(row)


class Recorded:
    """The models of one turn: the conductor's answer, the author's answers in order, the reply."""

    def __init__(self, conductor: Row | None = None, authors: list[Row] | None = None, reply: str = "") -> None:
        self.conductor, self.authors, self.reply = conductor, list(authors or []), reply
        self.calls: list[tuple[str, Row, int]] = []

    def ask(self, role: str, inp: Row, max_out: int) -> Row:
        self.calls.append((role, inp, max_out))
        if role == "conductor":
            if self.conductor is None:
                raise RuntimeError("no conductor answer recorded")
            return {k: v for k, v in self.conductor.items() if k != "by_code"}
        if not self.authors:
            return {"notes": "", "ops": [], "asks": [], "variants": []}
        return self.authors.pop(0)

    def say(self, inp: Row, max_out: int) -> Iterator[str]:
        self.calls.append(("reply", inp, max_out))
        yield from (self.reply or "Here you go.").split(" ")[:1]
        rest = " ".join((self.reply or "Here you go.").split(" ")[1:])
        if rest:
            yield " " + rest

    def roles(self) -> list[str]:
        return [c[0] for c in self.calls]


class RowsWorld:
    def __init__(self, *, revisions: bool = True, shots: list[Row] | None = None) -> None:
        d = data()
        self.data = d
        self.production, self.scene_id = str(d["scene"]["production_id"]), str(d["scene"]["id"])
        canon = [{**c, "kind": "character"} for c in d["characters"]]
        self.scenes = FakeScenes(production={**d["production"], "id": self.production}, scenes=[d["scene"]],
                                 lines=d["lines"], canon=canon, shots=shots if shots is not None else d["shots"])
        self.director = Director(self.scenes)
        self.revisions = FakeRevisions(missing=not revisions)
        self.thread = str(uuid4())
        self.user = str(uuid4())

    def ctx(self) -> RunContext:
        ports = replace(Ports(), scenes=self.scenes, director=self.director, revisions=self.revisions)
        return RunContext(production_id=UUID(self.production), actor_user_id=UUID(self.user), ports=ports)

    def payload(self, message: str, *, can_edit: bool = True) -> TurnPayload:
        uid = uuid4()
        self.director.history.append({"id": str(uid), "kind": "user", "text": message, "thread_id": self.thread,
                                      "blocks": []})
        return TurnPayload(production_id=UUID(self.production), scene_id=UUID(self.scene_id),
                           thread_id=UUID(self.thread), actor_user_id=UUID(self.user), actor_name="Dee",
                           can_edit=can_edit, can_edit_script=True, message=message, user_message_id=uid)

    def turn(self, message: str, models: Recorded | None = None, *, can_edit: bool = True,
             real_models: bool = False) -> dict[str, Any]:
        """One turn → {event: [data, ...]} (the message under "message")."""
        m = models or Recorded()
        seams = {} if real_models else {"ask": m.ask, "say": m.say}
        out: dict[str, Any] = {}
        for event, body in graph.run(self.payload(message, can_edit=can_edit), self.ctx(), **seams):
            out.setdefault(event, []).append(body)
        return out

    def act(self, kind: str, *, message_id: str | None = None, block: int = 0, option: int = 0,
            path: str = "", can_edit: bool = True) -> ZoraActionResult:
        req = ZoraAction(kind=kind,  # type: ignore[arg-type]
                         production_id=UUID(self.production), scene_id=UUID(self.scene_id),
                         actor_user_id=UUID(self.user), can_edit=can_edit, thread_id=UUID(self.thread),
                         message_id=UUID(message_id) if message_id else None, block=block, option=option, path=path)
        return graph.act(req, self.ctx())

    def cov(self) -> Coverage:
        return Coverage.from_rows(self.scenes.scene_rows[0], self.scenes.shots(self.scene_id),
                                  self.scenes.lines(self.scene_id), self.data["characters"])

    def last(self) -> Row:
        return dict(self.director.history[-1])


def block_of(message: Row, kind: str) -> tuple[int, Row]:
    return next((i, b) for i, b in enumerate(message.get("blocks") or []) if b.get("kind") == kind)
