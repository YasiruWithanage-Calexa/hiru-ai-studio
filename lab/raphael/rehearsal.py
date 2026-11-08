"""A scripted run of Raphael with NO model (plan/2026-11-08e phase 0a: the free part).

`Rehearsal` is a `Backend` that answers from DaVinci's hand-written Episode 1 tables (`davinci.rehearsal`: the moments, the
menu, the designs built from each clip's own fields). The script is the plan's: the edit plan, the bin a sequence at a time
(each clip complete, plan and design together), a `finish` that is REFUSED because two clips of one moment describe the
light differently, ONE `put_clips` that repairs both, and `finish` accepted. It runs the REAL loop, tools, checks, money
rules and page, so a paid run is not the first time any of them runs. The dollars are pretend (priced as gpt-5) and go to
a ledger of their own, never the lab's.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from davinci import checks
from davinci.brain import Call, Reply
from davinci.money import Usage
from davinci.rehearsal import MENU, MOMENTS, design, edit_plan, menu_entry, reading, sound

from .agent import Raphael

# two clips (in moments 5 and 6) whose first design uses another light, so the report names both and one call repairs both
BROKEN = {(5, "Q"), (6, "V")}


def complete(row: tuple, *, clip_id: str = "", broken: bool = False) -> dict[str, Any]:
    """One clip as Raphael writes it: the plan and the design together."""
    plan = menu_entry(row)
    return {"id": clip_id, **plan, "ir": design({**plan, "id": clip_id}, row[16], broken=broken), "sound": sound(plan)}


def sequence(letter: str) -> dict[str, Any]:
    rows = [r for r in MENU if MOMENTS[r[0]][0] == letter]
    return {"clips": [complete(r, broken=(r[0], r[2]) in BROKEN) for r in rows]}


class Rehearsal:
    """A `Backend` with no model. `bind(raphael)` lets the script read the run's state."""

    def __init__(self) -> None:
        self.i = 0
        self.agent: Raphael | None = None
        self.steps: list[tuple[str, Callable[[Raphael], dict[str, Any]]]] = self.script()

    def bind(self, agent: Raphael) -> None:
        self.agent = agent

    def script(self) -> list[tuple[str, Callable[[Raphael], dict[str, Any]]]]:
        def repair(a: Raphael) -> dict[str, Any]:
            """Every clip the report names, put back with its id and a corrected design, in ONE call."""
            named = sorted({i for f in checks.blocking(checks.check_all(a.reading, a.work)) for i in f.clips})
            out = []
            for clip_id in named:
                clip = a.work.by_id(clip_id)
                assert clip is not None
                row = next(r for r in MENU if (r[0], r[2], r[1]) == (clip.moment, clip.setup, clip.role))
                out.append(complete(row, clip_id=clip_id))
            return {"clips": out}

        return [
            ("write_edit_plan", lambda a: edit_plan()),
            ("put_clips", lambda a: sequence("A")),
            ("put_clips", lambda a: sequence("B")),
            ("put_clips", lambda a: sequence("C")),
            ("finish", lambda a: {"editor_notes": ["(too early: the report shows two faults)"]}),  # refused
            ("put_clips", repair),  # one batch repair of both clips
            ("finish", lambda a: {"editor_notes": [
                "Masters (setups B, H, K, P, U, V, G) are the cut; the Q and S singles are the only alternates.",
                "Avoided: a dolly zoom on the phone call (Veo is unreliable); the father is never shown; a speed ramp on the run is post only.",
                "Dialogue plays under the chosen audio: only the masters and the speakers' singles perform lines."]})]

    def step(self, *, system: str, items: list[dict[str, Any]], previous_id: str | None, tools: list[dict[str, Any]],
             model: str, effort: str, max_output: int) -> Reply:
        assert self.agent is not None, "bind() the agent first"
        if self.i >= len(self.steps):
            return Reply(id=f"r{self.i}", text="Done.", usage=Usage(2000, 1500, 100, 50))
        name, args = self.steps[self.i]
        self.i += 1
        return Reply(id=f"r{self.i}", calls=[Call(id=f"call{self.i}", name=name, args=json.dumps(args(self.agent)))],
                     usage=Usage(input_tokens=20_000, cached_tokens=15_000, output_tokens=9_000, reasoning_tokens=4_000))

    def structured(self, **_: Any) -> Reply:  # Raphael asks no other model
        raise AssertionError("Raphael never makes a structured worker call")


__all__ = ["Rehearsal", "complete", "reading", "sequence"]
