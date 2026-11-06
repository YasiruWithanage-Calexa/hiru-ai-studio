"""Zora's dependency graph (plan/2026-11-06e §4.3, from Nova Studio's `deps.py`): which parts of the plan an edit made
STALE, and the author tasks that follow.

    treatment.approach      → lens, angle, movement of every shot: "change only what now contradicts it"
    treatment.key_image     → one shot must deliver the new key image
    treatment.geography     → staging marks and frame sides (the 180° line is the gate's check)
    colour.* of sequence A  → the lighting of A's shots
    arc.* across blocks     → the sequences' bounds and the `why` of the shots at the turn
    sequence.add            → its colour entry (left empty by the kernel) and its title / purpose
    split / insert          → the new shot's reason and picture (size and lens too, if the author sees fit)
    merge                   → one picture for two
    remove / move / regroup → joins across the gap (code: the gate's checks)
    retime / use            → the Veo clock (code: the gate's mend and check); overruns REPORTED
    marks, last shots       → the end state → the next scene's seam (code: reported, a re-plan offered, never run)
    any shot                → its frame and its prompt are out of date (`stale`)

A TASK IS NEVER CREATED FROM HOW A MESSAGE READS: the conductor adds the tasks the person asked for; these come only
from changes code can prove. The re-cut guard (Nova `_recut_guard` / `RESHAPE_DIRTY_RATIO`) turns an edit that would
rewrite most of the scene into an offer.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from contracts.zora.tasks import Task, merge_tasks

# The effects a new or re-cut shot may be given on top of the ones it MUST get.
SHOT_DESIGN: tuple[str, ...] = ("shot.size", "shot.angle", "shot.lens", "shot.ir.setting", "shot.ir.cinematography",
                                "shot.ir.lighting", "shot.ir.subjects", "shot.ir.beats", "shot.ir.audio",
                                "shot.ir.first_frame", "shot.sound.ambience", "shot.sound.effects", "shot.sound.music",
                                "shot.sound.silence")
RESHAPE_DIRTY_RATIO = 0.5
RESHAPE_MIN_SHOTS = 3


@dataclass
class Stale:
    tasks: list[Task] = dc_field(default_factory=list)
    rewritten: set[str] = dc_field(default_factory=set)  # shots the author must write a new picture for
    removed: set[str] = dc_field(default_factory=set)
    stale: set[str] = dc_field(default_factory=set)  # shots whose frame / prompt is out of date
    joins: set[str] = dc_field(default_factory=set)  # shots that now meet a different shot (the gate checks them)
    end_touched: bool = False  # the end state may now differ: the seam with the next scene is checked


def plan_tasks(kernel: Any, changes: list[Any]) -> Stale:
    """The stale table above, over a batch of kernel `Change`s. `kernel` is the ZoraKernel after the batch."""
    out = Stale()
    live = set(kernel.handles())
    everything: tuple[str, ...] = ()
    last = kernel.handles()[-1] if kernel.handles() else ""
    for ch in changes:
        here = [h for h in ch.handles if h in live]
        kind, detail = ch.kind, ch.detail
        if kind == "treatment.set" and ch.field == "approach":
            out.tasks.append(Task(("shot.lens", "shot.angle", "shot.ir.cinematography"), everything,
                                  instruction=f"the approach is now: {detail.get('new', '')}. Change only the lenses, "
                                              "angles and camera movement that now contradict it; leave every other "
                                              "shot exactly as it is",
                                  reason="the approach changed", may=("shot.size", "shot.why")))
        elif kind == "treatment.set" and ch.field == "key_image":
            out.tasks.append(Task(("shot.ir.first_frame",), everything,
                                  instruction=f"the key image is now: {detail.get('new', '')}. One shot must deliver "
                                              "it; change only that shot's picture (and its size or lens if needed)",
                                  reason="the key image changed", may=("shot.size", "shot.lens", "shot.ir.beats",
                                                                       "shot.why")))
        elif kind == "treatment.set" and ch.field == "geography":
            out.tasks.append(Task(("staging.marks",), everything,
                                  instruction=f"the geography is now: {detail.get('new', '')}. Re-mark only the "
                                              "people whose side of frame now contradicts it; keep the 180° line",
                                  reason="the geography changed", may=("shot.ir.first_frame", "shot.ir.subjects")))
            out.end_touched = True
        elif kind == "colour.set":
            seq = str(detail.get("sequence") or "")
            if here:
                out.tasks.append(Task(("shot.ir.lighting",), tuple(here), sequence=seq,
                                      instruction=f"sequence {seq}'s {ch.field} is now: {detail.get('new', '')}. "
                                                  f"Change the lighting of its shots to match; the physical light "
                                                  "stays continuous across the scene",
                                      reason=f"the colour script of sequence {seq} changed",
                                      may=("shot.ir.first_frame",)))
                out.stale.update(here)
        elif kind in ("arc.set", "arc.add", "arc.remove"):
            spans = [(e or {}).get("blocks") for e in (detail.get("old"), detail.get("new")) if e]
            blocks = {b for s in spans if s for b in range(int(s["first"]), int(s["last"]) + 1)}
            at = tuple(h for h in kernel.handles() if set(kernel.shot(h)["blocks"]) & blocks)
            out.tasks.append(Task(("shot.why",), at,
                                  instruction="the arc changed: keep each sequence one movement of the arc, and "
                                              "rewrite only the reasons of the shots at the turn",
                                  reason="the arc moved", may=("sequence.bounds", "sequence.title",
                                                               "sequence.purpose")))
        elif kind == "sequence.add":
            seq = str(detail.get("sequence") or "")
            out.tasks.append(Task(("treatment.colour",), tuple(here), sequence=seq,
                                  instruction=f"sequence {seq} is new: give it its palette and grade (its light is "
                                              "the scene's, continuous) and a title and purpose if it has none",
                                  reason="a sequence has no colour yet", may=("sequence.title", "sequence.purpose")))
        elif kind == "split" and here:
            out.tasks.append(Task(("shot.why", "shot.ir.beats", "shot.ir.first_frame"), tuple(here),
                                  instruction="; ".join(p for p in (
                                      detail.get("intent", ""),
                                      "one shot was divided at a block boundary; it showed: " + str(detail.get("why")))
                                      if p),
                                  reason="a shot was divided in two", may=SHOT_DESIGN))
            out.rewritten.update(here)
            out.joins.update(here)
        elif kind == "insert" and here:
            out.tasks.append(Task(("shot.why", "shot.ir.beats", "shot.ir.first_frame"), tuple(here),
                                  instruction=f"a {detail.get('kind', 'shot')} was added: {detail.get('intent', '')}",
                                  reason="a new shot has no picture yet", may=SHOT_DESIGN))
            out.rewritten.update(here)
            out.joins.update(here)
        elif kind == "merge" and here:
            out.tasks.append(Task(("shot.why", "shot.ir.beats", "shot.ir.first_frame"), tuple(here),
                                  instruction="two shots were merged into one; give them ONE picture: "
                                              + " / ".join(w for w in detail.get("whys") or [] if w),
                                  reason="two shots were merged", may=SHOT_DESIGN))
            out.rewritten.update(here)
            out.joins.update(here)
        elif kind == "remove":
            out.removed.add(str(detail.get("removed") or ""))
            out.joins.update(here)
        elif kind in ("move", "regroup", "sequence.bounds", "sequence.remove"):
            out.joins.update(here)
        elif kind in ("mark.set", "mark.add", "mark.remove", "end.set"):
            out.end_touched = True
        if kind not in ("treatment.set", "arc.set", "arc.add", "arc.remove", "sequence.set", "lock", "unlock",
                        "zone.add", "end.set"):
            out.stale.update(here)
        if last and last in here:
            out.end_touched = True
    out.tasks = merge_tasks(out.tasks)
    return out


def dirty_ratio(before_count: int, stale: Stale) -> float:
    total = max(before_count, 1)
    return (len(stale.rewritten) + len(stale.removed)) / total


def recut_guard(lane: str, forced: str, before_count: int, stale: Stale, *, ratio: float = RESHAPE_DIRTY_RATIO,
                min_shots: int = RESHAPE_MIN_SHOTS) -> str:
    """→ why the edit is too big to be one ("" when it is not). Only an `edit` lane: `shape` and a lane the person
    forced (their answer to the offer) are exempt (Nova)."""
    if lane != "edit" or forced or before_count < min_shots:
        return ""
    moved = len(stale.rewritten) + len(stale.removed)
    if moved < min_shots or dirty_ratio(before_count, stale) <= ratio:
        return ""
    return f"it would rewrite {moved} of the scene's {before_count} shots."
