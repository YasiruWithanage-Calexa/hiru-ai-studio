"""A production in memory with Episode 1 (the lab's scene, 60 s) as its one scene, for the system and the writer
(fakes only),
and the scripted conversations the gold bins make: a model that plays run 3 (stage 1) and pass 5 (stage 2) tool call
by tool
call, so the whole product code runs without a model."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage

from contracts import sceneplan, stagemap
from contracts.jobs import DispatchPayload, JobKind
from contracts.raphael.bin import Bin
from contracts.raphael.stored import StoredRaphael
from contracts.raphael.wire import Clip
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeJobs, FakeScenes, FakeSplit
from hiru_ai.core.testing import RoutedChatModel
from tests.raphael import gold

PEOPLE = {"Kasun": "C01", "Anudi": "C02", "Father": "C03", "Narrator": "C04"}


def canon_rows(production: str) -> list[dict[str, Any]]:
    rows = [
        {
            "id": f"char-{name}",
            "production_id": production,
            "kind": "character",
            "name": name,
            "code": code,
            "aliases": [],
            "current": {
                "version": 1,
                "card": {"summary": f"{name} in the drama", "appearance": f"{name}, 25"},
                "wardrobe_anchor": "",
                "voice_pin": f"{name}'s voice",
            },
        }
        for name, code in PEOPLE.items()
    ]
    rows.append(
        {
            "id": "loc-1",
            "production_id": production,
            "kind": "location",
            "name": "A Colombo roadside",
            "code": "L01",
            "aliases": [],
            "current": {"version": 1, "card": {"look": "road, rain"}},
        }
    )
    rows += [
        {
            "id": f"prop-{o}",
            "production_id": production,
            "kind": "prop",
            "name": o,
            "code": f"P-{o}",
            "aliases": [],
            "current": {"version": 1, "card": {}},
        }
        for o in ("phone", "tea", "umbrella")
    ]
    return rows


class World:
    """One episode with one scene: Episode 1 of the lab, 60 s."""

    def __init__(
        self,
        *,
        status: str = "draft",
        shots: list[dict[str, Any]] | None = None,
        settings: dict | None = None,
        staging: str = "person",
    ):
        """`staging`: the scene's state map (plan/2026-11-09): "person" is the gold ledger as a person's map (no stager
        call), "" none (the stager is asked)."""
        self.staging = staging
        self.production, self.episode = str(uuid4()), str(uuid4())
        self.scene_rows: list[dict[str, Any]] = []
        self.line_rows: list[dict[str, Any]] = []
        self.line_ids: dict[int, str] = {}
        self.scene_id = self.add_scene(1, status=status)
        self.scenes = FakeScenes(
            production={"id": self.production, "settings": settings or {}},
            scenes=self.scene_rows,
            lines=self.line_rows,
            canon=canon_rows(self.production),
            shots=shots,
        )
        self.split = FakeSplit(
            episodes=[{"id": self.episode, "number": 1, "title": "Ep 1", "synopsis": "", "status": "draft"}],
            scenes=self.scene_rows,
            characters=[c for c in self.scenes.canon_rows if c["kind"] == "character"],
            locations=[c for c in self.scenes.canon_rows if c["kind"] == "location"],
        )
        self.jobs = FakeJobs()

    def add_scene(self, number: int, *, status: str = "draft") -> str:
        blocks = gold.scene().blocks
        sid = str(uuid4())
        ids = {b.index: str(uuid4()) for b in blocks if b.line_id}
        self.line_ids = ids
        script = [
            {"kind": "dialogue", "line_id": ids[b.index]}
            if b.line_id
            else {"kind": b.kind, "text": b.text, "screen": b.screen, "events": b.events, "by": "person"}
            for b in blocks
        ]
        self.scene_rows.append(
            {
                "id": sid,
                "production_id": self.production,
                "episode_id": self.episode,
                "number": number,
                "heading": f"Scene {number}",
                "title": "",
                "location_id": "loc-1",
                "envelope_s": 60,
                "script": script,
                "status": status,
                "note": "",
                "script_version": 1,
                "time_of_day": "DAY",
                "raphael": {},
            }
        )
        new_lines = []
        for n, b in enumerate(b for b in blocks if b.line_id):
            speaker = b.speaker if b.speaker in PEOPLE else "Narrator"
            new_lines.append(
                {
                    "id": ids[b.index],
                    "production_id": self.production,
                    "scene_id": sid,
                    "ord": n,
                    "speaker": b.speaker,
                    "character_id": f"char-{speaker}",
                    "text": b.text,
                    "delivery": b.delivery,
                }
            )
        self.line_rows += new_lines
        if self.staging:
            items = sceneplan.items_for(script, new_lines)
            made = stagemap.validate(gold.staging_raw(), items, ["Kasun", "Anudi"], version=1, by=self.staging)
            self.scene_rows[-1]["staging"] = made.model_dump(mode="json")
        return sid

    def short_ids(self) -> dict[str, str]:
        return {f"L{i}": real for i, real in self.line_ids.items()}

    def ctx(self) -> RunContext:
        return RunContext(ports=replace(Ports(), jobs=self.jobs, scenes=self.scenes, split=self.split))

    def payload(self, kind: JobKind = JobKind.PLAN_SCENE_RAPHAEL, **state: Any) -> DispatchPayload:
        """A new job (the fakes forget the last one: a finished job is skipped, as in production)."""
        self.jobs = FakeJobs()
        return DispatchPayload(
            job_id=uuid4(),
            kind=kind,
            actor_user_id=uuid4(),
            production_id=UUID(self.production),
            pipeline=[kind],
            cursor=0,
            state={"scene_ids": [self.scene_id], **state},
        )

    def row(self) -> dict[str, Any]:
        return next(r for r in self.scenes.scene_rows if str(r["id"]) == self.scene_id)

    def shots(self) -> list[dict[str, Any]]:
        return self.scenes.shots(self.scene_id)

    def stored(self) -> StoredRaphael:
        found = StoredRaphael.load(self.row()["raphael"])
        assert found is not None
        return found


# ── the scripted conversations ───────────────────────────────────────────────────────────────────


def call(name: str, args: dict[str, Any], n: int = 0) -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}-{n}", "type": "tool_call"}]
    )


def wire(clip: Clip, **extra: Any) -> dict[str, Any]:
    """A bin clip as the model sends it: a new clip (id ""), no slate, stage or anchor of stage 1."""
    row = {k: v for k, v in clip.model_dump(mode="json").items() if k not in ("slate", "stage", "anchor", "blend")}
    return {**row, "id": "", **extra}


def stage1_turns(*, finish: bool = True) -> list[AIMessage]:
    """Run 3's conversation: the edit plan, the must clips a sequence at a time (in id order, so the ids are the
    gold's),
    then finish."""
    work = gold.stage1()
    assert work.edit is not None
    clips = sorted(work.clips, key=lambda c: c.id)
    turns = [call("write_edit_plan", work.edit.model_dump(mode="json"))]
    # Run 3 added a clip as c09 and took it out again, so the gold ids skip it: the second call adds a copy of c08 as
    # c09 and
    # a later call removes it, which keeps every id the gold stage 2 anchors on.
    first_eight = [c for c in clips if int(c.id[1:]) <= 8]
    rest = [c for c in clips if int(c.id[1:]) > 8]
    cuts = [first_eight[:5], [*first_eight[5:], first_eight[-1]], rest]
    for n, part in enumerate(cuts):
        turns.append(call("put_clips", {"clips": [wire(c) for c in part]}, n))
    turns.append(call("remove_clips", {"clip_ids": ["c09"]}))
    if finish:
        turns.append(call("finish", {"editor_notes": list(work.edit.editor_notes)}))
    return turns


def stage2_turns(*, finish: bool = True) -> list[AIMessage]:
    """Pass 5's conversation: the 8 cinematic clips in one call, then finish with its blend notes and moment review."""
    final = gold.final()
    notes, review = gold.stage2_result()
    turns = [
        call(
            "put_extras",
            {
                "clips": [
                    wire(c, anchor=list(c.anchor), blend=c.blend) for c in sorted(final.extras(), key=lambda c: c.id)
                ]
            },
        )
    ]
    if finish:
        turns.append(call("finish", {"blend_notes": notes, "moment_review": [r.model_dump() for r in review]}))
    return turns


def model_for(*turns: list[AIMessage]) -> RoutedChatModel:
    """One scripted model for a whole run: the conversations' turns, in order."""
    queue = [t for part in turns for t in part]
    return RoutedChatModel(routes={"all": queue}, choose=lambda m: "all")


def stored_stage1(world: World | None = None) -> StoredRaphael:
    """The result of a finished stage 1 (run 3's bin), as the database holds it."""
    work: Bin = gold.stage1()
    return StoredRaphael(
        stage1="finished",
        stage2="none",
        cap=2,
        edit=work.edit,
        clips=work.clips,
        line_ids=world.short_ids() if world else {},
        editor_notes=list(work.edit.editor_notes) if work.edit else [],
    )
