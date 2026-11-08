"""A scripted run of stage 2, the cinematic pass, with NO model (plan/2026-11-08e phase 0c: the free part).

It runs on run 3's finished must bin (13 must clips, 70 s; loaded from disk, no stage 1 call) through the REAL loop, tools,
checks, money rules and page. The script is the plan's: an extra on a must id refused, a same-angle extra refused, three
over one moment refused (with a refused `finish`), ONE `put_extras` that repairs both, `finish` accepted with a blend note
per clip. The dollars are pretend and go to a ledger of their own, never the lab's.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from davinci.brain import Call, Reply
from davinci.money import Usage
from davinci.state import Bin

from . import stage2

RUN3 = Path(__file__).resolve().parent / "runs" / "3-gpt_5_high_episode1"


def extra(work: Bin, anchor_id: str, *, role: str, technique: str, blend: str, size: str, setup: str, priority: str, why: str,
          action: str, own_setting: str = "", clip_id: str = "") -> dict[str, Any]:
    """One cinematic clip as the pass writes it: a whole clip (plan + design), anchored, silent, in the moment's own words."""
    anchor = work.by_id(anchor_id)
    assert anchor is not None and anchor.ir is not None, anchor_id
    look = stage2.looks(work)[anchor.moment]
    setting = own_setting or look["setting"]
    shown = [] if role in ("establishing", "atmosphere") else list(look["people"].items())[:1]
    move = technique.replace("_", " ")
    cam = {"camera": "cinema camera on a light rig", "angle": "eye level", "framing": f"{size}: {why}",
           "movement": f"{move}, one continuous path", "white_balance": "5600K overcast daylight",
           "color_tone": "as the anchor", "depth_of_field": "shallow" if size in ("INSERT", "ECU", "CU") else "deep",
           "lens_artifacts": "none"}
    subjects = [{"id": pid, "description": desc, "action": action, "position": "where the anchor places them"}
                for pid, desc in shown]
    beats = [{"time": "0-1s", "camera": f"{size}, settled", "director_line": "Hold the frame before the move.",
              "action": "The frame holds.", "performance": "Stillness; breath visible."},
             {"time": "1-3s", "camera": move, "director_line": why, "action": action or "The place under the rain.",
              "performance": "Eyes lower, then lift." if shown else "The place carries it."},
             {"time": "3-4s", "camera": "settled", "director_line": "Let it land.", "action": "The frame settles.",
              "performance": "Lips closed; stillness."}]
    ir = {"setting": setting, "cinematography": cam, "lighting": look["lighting"], "subjects": subjects, "beats": beats,
          "audio": str(anchor.ir.get("audio") or ""),
          "first_frame": {"composition": f"{size} frame for the {role}.", "subjects": [f"{pid} as in the anchor" for pid, _ in shown],
                          "setting": setting, "lighting": look["lighting"]}}
    snd = anchor.sound.model_dump() if anchor.sound else {"ambience": "", "effects": "", "music": "none", "silence": False}
    return {"id": clip_id, "moment": anchor.moment, "role": role, "setup": setup, "blocks": [], "lines": [], "speaks": False,
            "over": "", "size": size, "angle": "eye level", "lens": "85mm for a close detail" if size in ("INSERT", "ECU") else "24mm",
            "technique": technique, "why": why, "take_s": 4, "handle_in_s": 1.0, "handle_out_s": 1.0, "priority": priority,
            "editor_note": f"{blend} with {anchor_id}", "ir": ir, "sound": snd, "anchor": [anchor_id], "blend": blend}


def on_must(a: stage2.CinematicPass) -> dict[str, Any]:
    """A clip sent with a must clip's id: refused, nothing changes."""
    return {"clips": [extra(a.work, "c05", role="insert", technique="rack_focus", blend="cut_in", size="INSERT", setup="E",
                            priority="should", why="A detail of the moment.", action="hands still", clip_id="c05")]}


def first(a: stage2.CinematicPass) -> dict[str, Any]:
    """Five clips: a drone open (good), a same-angle single on c07 (refused) and three more on moment 7 (four: refused)."""
    return {"clips": [
        extra(a.work, "c01", role="establishing", technique="drone_establishing", blend="open", size="EWS", setup="M",
              priority="nice", why="The street under the rain from above, before we meet him: the size of his world.",
              action="", own_setting="A Colombo roadside from high above, the stall a small light in the rain."),
        extra(a.work, "c07", role="single", technique="locked_off", blend="under_line", size="MS", setup="F", priority="should",
              why="Another take of his answer.", action="looks at her, lips closed"),
        extra(a.work, "c07", role="insert", technique="rack_focus", blend="cut_in", size="INSERT", setup="N", priority="should",
              why="Focus moves from the flask to his hand: the stall is what he has.", action="his hand rests on the flask"),
        extra(a.work, "c07", role="reaction", technique="slow_creep", blend="under_line", size="CU", setup="P", priority="nice",
              why="We creep into his face as his aim lands.", action="listens, lips closed"),
        extra(a.work, "c07", role="cutaway", technique="foreground_framing", blend="under_line", size="MS", setup="R",
              priority="nice", why="The rain on the awning frames him while he talks of his aim.", action="stands at the counter")]}


def repair(a: stage2.CinematicPass) -> dict[str, Any]:
    """The same-angle clip, rewritten as an extreme close-up of the phone on the call (moment 8): it now differs from its anchor
    and leaves moment 7 with three. ONE call cures both faults."""
    same = next(c for c in stage2.extras(a.work) if c.role == "single")
    return {"clips": [extra(a.work, "c08", role="insert", technique="shallow_isolation", blend="cut_in", size="INSERT",
                            setup="Q", priority="should", clip_id=same.id,
                            why="Her grip tightens on the phone: the call is cold before her face shows it.",
                            action="her hand holds the phone to her ear")]}


def notes(a: stage2.CinematicPass) -> dict[str, Any]:
    assert a.work.edit is not None
    has = {e.moment for e in stage2.extras(a.work)}
    review = [{"moment": m.n, "earns": m.n in has,
               "why": "it turns the scene" if m.n in has else "plain coverage: the must clip carries it"} for m in a.work.edit.moments]
    return {"blend_notes": [f"{e.id} ({e.slate}): {e.blend} with {', '.join(e.anchor)}; {e.why}" for e in stage2.extras(a.work)],
            "moment_review": review}


SCRIPT: list[tuple[str, Callable[[stage2.CinematicPass], dict[str, Any]]]] = [
    ("put_extras", on_must), ("put_extras", first), ("finish", lambda a: {"blend_notes": ["(too early)"], "moment_review": []}),
    ("put_extras", repair), ("finish", notes)]


class CinematicRehearsal:
    """A `Backend` with no model. `bind(pass_)` lets the script read the run's state."""

    def __init__(self) -> None:
        self.i = 0
        self.agent: stage2.CinematicPass | None = None

    def bind(self, agent: stage2.CinematicPass) -> None:
        self.agent = agent

    def step(self, *, system: str, items: list[dict[str, Any]], previous_id: str | None, tools: list[dict[str, Any]],
             model: str, effort: str, max_output: int) -> Reply:
        assert self.agent is not None, "bind() the agent first"
        if self.i >= len(SCRIPT):
            return Reply(id=f"r{self.i}", text="Done.", usage=Usage(2000, 1500, 100, 50))
        name, args = SCRIPT[self.i]
        self.i += 1
        return Reply(id=f"r{self.i}", calls=[Call(id=f"call{self.i}", name=name, args=json.dumps(args(self.agent)))],
                     usage=Usage(input_tokens=30_000, cached_tokens=25_000, output_tokens=6_000, reasoning_tokens=3_000))

    def structured(self, **_: Any) -> Reply:
        raise AssertionError("the cinematic pass never makes a structured worker call")


__all__ = ["RUN3", "SCRIPT", "CinematicRehearsal", "extra"]
