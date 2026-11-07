"""The turn's ONE change ledger (plan/2026-11-06e §4.6, §4.10; Nova W2, W5, W7).

Everything the reply may say about what happened comes from here, and the interface shows the same thing under the
reply ("What changed"). Ordered by how much a person cares: what changed; their own request not applied; the team's work
that was refused; what they asked for that did not change; and, when the turn tried to write and landed nothing,
NOTHING CHANGED, said plainly (W2: a turn that changed nothing was indistinguishable from one that worked, and the reply
filled the silence with work it assumed had happened).

    Ledger.event()     the `ops` event: {changes, refused, undelivered, nothing_changed} (the client reads only `true`)
    Ledger.gate()      the `gate` event: {problems, overruns, seams}
    Ledger.context()   the blocks the reply is given, LAST in its prompt

Pure standard library + pydantic.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Level = Literal["treatment", "sequence", "shot", "staging", "end", "lock"]


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Level
    where: str  # "Treatment", "Sequence B", "S03", "Staging", "End state"
    text: str  # what changed, in plain words
    by: str = ""  # conductor | author | repair | person | code


class Ledger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: list[Line] = []
    refused: list[str] = []  # the person's own request, not applied, with the reason
    team_refused: list[str] = []  # the author's work code refused (a lock, outside its task); a dropped no-op is not
    undelivered: list[str] = []  # declared effects that did not change, as a person reads them
    attempted: bool = False  # the turn tried to write (an op, a task, or the author ran)
    staged: list[str] = []  # cards waiting for the person (a line change, a translation)
    mended: list[str] = []  # what code fixed after the edit (a longer take, a split at a block)
    problems: list[str] = []  # faults this turn introduced and could not clear: reported, never blocking
    already: list[str] = []  # faults the plan had BEFORE this turn (a script edited after planning): never blocking
    overruns: list[str] = []  # a line longer than its take: reported with the way out, NEVER trimmed
    seams: list[str] = []  # the join with the next scene this turn broke
    stale: list[str] = []  # shots whose frame or prompt is now out of date
    offer: str = ""  # a change too big for an edit, offered as "Re-plan with Jonathan" instead
    undone: bool = False  # the turn's edit was undone (a re-cut offered instead)

    @property
    def nothing_changed(self) -> bool:
        return not any(c.level != "lock" for c in self.changes)

    def event(self) -> dict[str, object]:
        return {"changes": [c.model_dump() for c in self.changes], "refused": [*self.refused, *self.team_refused],
                "undelivered": list(self.undelivered), "nothing_changed": self.nothing_changed,
                "staged": list(self.staged), "mended": list(self.mended), "stale": list(self.stale)}

    def gate(self) -> dict[str, object]:
        return {"problems": list(self.problems), "overruns": list(self.overruns), "seams": list(self.seams),
                "already": list(self.already)}

    def context(self) -> list[str]:
        """The reply's account of the turn. Stated to outrank the conversation: an earlier message saying something was
        done before is not evidence about THIS turn."""
        parts: list[str] = []
        if self.changes:
            parts.append("DONE THIS TURN (computed by code from the plan; true even if the conversation says "
                         "otherwise; describe it as done now, in plain words):\n"
                         + "\n".join(f"- {c.where}: {c.text}" for c in self.changes[:16]))
        if self.mended:
            parts.append("CODE THEN FIXED (say it briefly):\n" + "\n".join(f"- {m}" for m in self.mended[:6]))
        if self.refused:
            parts.append("REQUESTED BUT NOT APPLIED (the person asked for this and did not get it: say so, and why):\n"
                         + "\n".join(f"- {r}" for r in self.refused[:8]))
        if self.team_refused:
            parts.append("THE TEAM'S OWN WORK THAT COULD NOT BE APPLIED (none of this happened; never describe any of "
                         "it as done):\n" + "\n".join(f"- {r}" for r in self.team_refused[:6]))
        if self.undelivered:
            parts.append("ASKED FOR THIS TURN BUT NOT CHANGED (never say these were done or imply it; say plainly "
                         "which did not happen and offer one concrete next step):\n"
                         + "\n".join(f"- {u}" for u in self.undelivered))
        if self.overruns:
            parts.append("LINES LONGER THAN THEIR TAKE (reported, never trimmed: give the way out as written):\n"
                         + "\n".join(f"- {o}" for o in self.overruns))
        if self.problems:
            parts.append("LEFT FOR THE PERSON (code could not clear these this turn):\n"
                         + "\n".join(f"- {p}" for p in self.problems[:6]))
        if self.already:
            parts.append("ALREADY IN THE PLAN BEFORE THIS TURN (not caused by this turn and did NOT stop it; mention "
                         "it once, briefly, as a separate note: the script has probably changed since the scene was "
                         "planned, and re-planning the scene with Jonathan fixes it):\n"
                         + "\n".join(f"- {a}" for a in self.already[:4]))
        if self.seams:
            parts.append("THE NEXT SCENE'S START NO LONGER MATCHES (say so; a re-plan of the next scene can be "
                         "offered, never claimed):\n" + "\n".join(f"- {s}" for s in self.seams))
        if self.staged:
            parts.append("WAITING FOR THE PERSON'S YES (a card; nothing in the script changed yet):\n"
                         + "\n".join(f"- {s}" for s in self.staged))
        if self.offer:
            parts.append(f"OFFERED, NOT DONE: {self.offer} Ask whether to re-plan the scene with Jonathan; the plan is "
                         "as it was.")
        if self.nothing_changed and self.attempted and not self.offer:
            parts.append("NOTHING CHANGED THIS TURN. The plan is exactly as it was before this message: not one field "
                         "was written. You may NOT say you adjusted, added, removed, rewrote, tightened or updated "
                         "anything. Say plainly that nothing was changed, give the reason if one is listed above and "
                         "otherwise ask for it put a different way, and offer one concrete next step.")
        return parts
