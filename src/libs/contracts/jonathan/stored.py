"""What Shot Planner Jonathan keeps on a scene (`scenes.jonathan`, plan/2026-11-05e §4.6, §7).

The shots rows carry each shot (card, IR, design); the scene carries the rest: the author's plan as written, what code
mended and what a repair changed, what is still reported, the end state the next scene starts from, the look changes
code worked out (D9), the link to the scene before and the additions a person removed (never added back).

    StoredPlan.load(raw)       → the stored plan, or None for a scene Jonathan never planned (the column is `{}`)
    StoredPlan.data()          → the JSON `scenes.jonathan` holds
    Removed.of(plan, added)    → how a removed addition is remembered across re-plans (shot numbers change, it does not)

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.jonathan.plan import Problem, norm
from contracts.jonathan.wire import AddedW, EndStateW, JonathanWire

STORED_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Removed(_Model):
    """An addition a person took out. Remembered as its kind and the block it came after, not by shot number."""

    kind: str
    after_block: int  # the last script block shown at or before the shot (-1 = before the first)
    what: str = ""

    @classmethod
    def of(cls, plan: JonathanWire, added: AddedW) -> Removed:
        return cls(kind=added.kind, after_block=after_block(plan, added.shot), what=added.what)

    def matches(self, plan: JonathanWire, added: AddedW) -> bool:
        return norm(added.kind) == norm(self.kind) and after_block(plan, added.shot) == self.after_block


def after_block(plan: JonathanWire, number: int) -> int:
    """The last script block any shot up to and including shot `number` shows."""
    shown = [b for s in plan.shots if s.n <= number for b in s.blocks]
    return max(shown, default=-1)


class LookChange(_Model):
    """A person's look at a scene's end differs from its start (D9): a costume change, an injury, a wet shirt."""

    who: str
    scene: int  # the scene number the change happens in
    before: str
    after: str


class Link(_Model):
    """How this scene follows the one before: `continuous` (everything passes on), `carry` (looks and what people keep
    pass on; place, position and light do not), or `""` (it starts from canon). `by` says who decided."""

    kind: Literal["", "continuous", "carry"] = ""
    by: Literal["rules", "person"] = "rules"


class StoredPlan(_Model):
    version: int = STORED_VERSION
    planner: Literal["jonathan"] = "jonathan"
    job_id: str = ""
    # A hash of what Jonathan was given for this scene (script, lines, cast, start state, removed additions): a rebuild
    # whose hash is unchanged keeps this plan instead of planning again (plan §4.4). "" = unknown.
    input_hash: str = ""
    plan: JonathanWire  # the plan in use: mended and repaired
    link: Link = Link()
    start: EndStateW | None = None  # the state this scene was planned from (the end state before it, or canon looks)
    removed: list[Removed] = []
    line_ids: dict[str, str] = {}  # the agent-facing id (L4) → the dialogue line's id
    mended: list[str] = []  # what code fixed, in sentences
    # per revise pass (the stabiliser's, a seam's or a person's note): what was sent (the problems and the craft gaps),
    # the score that came back, whether code kept it
    repairs: list[dict[str, Any]] = []
    problems: list[Problem] = []  # what is left: reported, never failed (plan §6)
    # the craft measures of the plan in use (`contracts.jonathan.measures.Measure` as JSON): reported, never blocking
    measures: list[dict[str, Any]] = []
    seams: list[Problem] = []  # the join with the scene before (and after, when it is already planned)
    look_changes: list[LookChange] = []
    end_state: EndStateW | None = None
    # The shot list that was on the scene when Jonathan first planned it, kept so a person can compare the two side by
    # side: `{"planner", "shots": [...]}`.
    previous: dict[str, Any] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)

    def is_removed(self, plan: JonathanWire, added: AddedW) -> bool:
        return any(r.matches(plan, added) for r in self.removed)

    def data(self) -> dict[str, Any]:
        """The JSON `scenes.jonathan` holds."""
        return dict(self.model_dump(mode="json"))

    @classmethod
    def load(cls, raw: Any) -> StoredPlan | None:
        """The stored plan of a scene row's `jonathan` column; None when the scene was not planned by Jonathan (the
        column is
        `{}`) or holds something this version cannot read."""
        if not isinstance(raw, dict) or raw.get("planner") != "jonathan":
            return None
        try:
            return cls.model_validate(raw)
        except ValueError:
            return None
