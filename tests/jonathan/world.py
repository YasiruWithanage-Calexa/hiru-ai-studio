"""A production in memory with the gold phone call as its one scene, for the system and the writer (fakes only)."""
from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from contracts.jobs import DispatchPayload, JobKind
from contracts.jonathan.stored import StoredPlan
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeJobs, FakeScenes, FakeSplit
from tests.jonathan import gold

PEOPLE = {"Anudi": "C01", "Dasun": "C02", "Father": "C03", "Kasun": "C04"}


def canon_rows(production: str, version: int = 1) -> list[dict[str, Any]]:
    rows = [{"id": f"char-{name}", "production_id": production, "kind": "character", "name": name, "code": code,
             "aliases": [], "current": {"version": version, "card": {"summary": f"{name} in the drama",
                                                                      "appearance": f"{name}, 25"},
                                        "wardrobe_anchor": "", "voice_pin": f"{name}'s voice"}}
            for name, code in PEOPLE.items()]
    rows.append({"id": "loc-1", "production_id": production, "kind": "location", "name": "A bench by the lake",
                 "code": "L01", "aliases": [], "current": {"version": version, "card": {"look": "bench, lake"}}})
    rows += [{"id": f"prop-{o}", "production_id": production, "kind": "prop", "name": o, "code": f"P-{o}",
              "aliases": [], "current": {"version": version, "card": {}}} for o in ("bench", "phone", "bag")]
    return rows


class World:
    """One episode; the scenes are the gold scene `name` (and optionally more, for a chain)."""

    def __init__(self, name: str = gold.NAME, *, status: str = "draft", time_of_day: str = "DAY",
                 shots: list[dict[str, Any]] | None = None) -> None:
        self.production, self.episode = str(uuid4()), str(uuid4())
        self.scene_rows: list[dict[str, Any]] = []
        self.line_rows: list[dict[str, Any]] = []
        self.line_ids: dict[str, dict[int, str]] = {}
        self.name = name
        self.add_scene(1, name, status=status, time_of_day=time_of_day)
        self.scene_id = str(self.scene_rows[0]["id"])
        self.scenes = FakeScenes(production={"id": self.production, "settings": {}}, scenes=self.scene_rows,
                                 lines=self.line_rows, canon=canon_rows(self.production), shots=shots)
        self.split = FakeSplit(
            episodes=[{"id": self.episode, "number": 1, "title": "Ep 1", "synopsis": "", "status": "draft"}],
            scenes=self.scene_rows, characters=[c for c in self.scenes.canon_rows if c["kind"] == "character"],
            locations=[c for c in self.scenes.canon_rows if c["kind"] == "location"])
        self.jobs = FakeJobs()

    def add_scene(self, number: int, name: str = gold.NAME, *, status: str = "draft", time_of_day: str = "DAY",
                  location: str = "loc-1") -> str:
        sc = gold.raw(name)
        sid = str(uuid4())
        ids = {b["index"]: str(uuid4()) for b in sc["blocks"] if b.get("line_id")}
        self.line_ids[sid] = ids
        script = [{"kind": "dialogue", "line_id": ids[b["index"]]} if b.get("line_id")
                  else {"kind": b["kind"], "text": b["text"]} for b in sc["blocks"]]
        self.scene_rows.append({
            "id": sid, "production_id": self.production, "episode_id": self.episode, "number": number,
            "heading": f"Scene {number}", "title": "", "location_id": location, "envelope_s": 90, "script": script,
            "status": status, "note": "", "script_version": 1, "time_of_day": time_of_day, "jonathan": {}})
        n0 = len(self.line_rows)
        for n, b in enumerate(b for b in sc["blocks"] if b.get("line_id")):
            speaker = "Father" if b["speaker"].startswith("Father") else b["speaker"]
            self.line_rows.append({
                "id": ids[b["index"]], "production_id": self.production, "scene_id": sid, "ord": n0 + n,
                "speaker": b["speaker"], "character_id": f"char-{speaker}", "text": b["text"],
                "delivery": b.get("delivery", "")})
        if hasattr(self, "scenes"):  # the fakes hold copies of what they were built with
            self.scenes.scene_rows, self.scenes.line_rows = self.scene_rows, self.line_rows
        return sid

    def short_ids(self, scene_id: str | None = None) -> dict[str, str]:
        """The author's short line ids (L<block>) → the dialogue lines' real ids."""
        return {f"L{i}": real for i, real in self.line_ids[scene_id or self.scene_id].items()}

    def ctx(self) -> RunContext:
        return RunContext(ports=replace(Ports(), jobs=self.jobs, scenes=self.scenes, split=self.split))

    def payload(self, **state: Any) -> DispatchPayload:
        """A new job (the fakes forget the last one: a finished job is skipped, as in production)."""
        self.jobs = FakeJobs()
        return DispatchPayload(job_id=uuid4(), kind=JobKind.PLAN_SCENE_JONATHAN, actor_user_id=uuid4(),
                               production_id=UUID(self.production), pipeline=[JobKind.PLAN_SCENE_JONATHAN], cursor=0,
                               state={"scene_ids": [self.scene_id], **state})

    def row(self, scene_id: str | None = None) -> dict[str, Any]:
        sid = scene_id or self.scene_id
        return next(r for r in self.scenes.scene_rows if str(r["id"]) == sid)

    def shots(self, scene_id: str | None = None) -> list[dict[str, Any]]:
        return self.scenes.shots(scene_id or self.scene_id)

    def stored(self, scene_id: str | None = None) -> StoredPlan:
        found = StoredPlan.load(self.row(scene_id)["jonathan"])
        assert found is not None
        return found
