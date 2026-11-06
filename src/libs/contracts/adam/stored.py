"""What Shot Planner Adam keeps on a scene (`scenes.adam`, plan/2026-11-04b §5.1, §5.5).

The shots rows carry each card (`shots.card`), so everything after the plan keeps working. The scene carries the rest:
the analysis, the treatment that was chosen and the two that were not (one click away), the moments, the staging, the
sound map, what code and the screening panel said, and the elaborations a person removed (which are never added back).

    StoredPlan.of(plan, ...)   → what `adam_write` stores
    StoredPlan.plan()          → the AdamPlan to show, edit or re-write
    Removed.of(moment)         → how a removed elaboration is remembered across re-plans (ids change, it does not)

Pure standard library + pydantic (the `contracts` rule).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.adam.plan import AdamPlan, Moment, SceneAnalysis, ShotCard, SoundMap, Staging, Treatment, norm

STORED_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Removed(_Model):
    """An elaboration a person took out. Remembered as its kind and the blocks it served, not by id: a re-plan writes
    new ids, and the same addition must not come back."""

    kind: str
    blocks: list[int] = []
    seen: str = ""

    @classmethod
    def of(cls, moment: Moment) -> Removed:
        return cls(kind=moment.kind, blocks=sorted(moment.blocks), seen=moment.seen)

    def matches(self, moment: Moment) -> bool:
        return (moment.tier != "script" and norm(moment.kind) == norm(self.kind)
                and sorted(moment.blocks) == self.blocks)


class StoredPlan(_Model):
    version: int = STORED_VERSION
    planner: Literal["adam"] = "adam"
    job_id: str = ""
    # A hash of what Adam was given for this scene (the script, its context, the elaborations a person removed, the
    # mode): a rebuild whose hash is unchanged keeps this plan instead of planning again (plan/2026-11-05 L5).
    # "" = unknown.
    input_hash: str = ""
    chosen: str = ""  # the stance of the treatment in use
    chosen_by: Literal["score", "person", "model"] = "score"  # "model": the one take chose (plan/2026-11-05)
    analysis: SceneAnalysis
    treatment: Treatment  # the one in use, with its moment ids bound
    alternates: list[Treatment] = []  # the other stances, as the director wrote them: switching one re-plans the cards
    moments: list[Moment]
    staging: Staging = Staging()
    cards: list[ShotCard] = []
    sound_map: SoundMap = SoundMap()
    removed: list[Removed] = []
    line_ids: dict[str, str] = {}  # the agent-facing id (L1) → the dialogue line's id
    report: dict[str, Any] = Field(default_factory=dict)
    # The shot list that was on the scene when Adam first planned it (the classic planner's, usually), kept so a person
    # can compare the two side by side: `{"planner", "shots": [{number, title, framing, duration_s, ...}]}`.
    previous: dict[str, Any] = Field(default_factory=dict)

    def plan(self) -> AdamPlan:
        return AdamPlan(analysis=self.analysis, treatment=self.treatment, moments=self.moments, staging=self.staging,
                        cards=self.cards, sound_map=self.sound_map, report=self.report)

    def moment(self, ident: str) -> Moment | None:
        return next((m for m in self.moments if m.id == ident), None)

    def is_removed(self, moment: Moment) -> bool:
        return any(r.matches(moment) for r in self.removed)

    def data(self) -> dict[str, Any]:
        """The JSON `scenes.adam` holds."""
        return dict(self.model_dump(mode="json", by_alias=True))

    @classmethod
    def load(cls, raw: Any) -> StoredPlan | None:
        """The stored plan of a scene row's `adam` column; None when the scene was not planned by Adam (the column is
        `{}`) or holds something this version cannot read."""
        if not isinstance(raw, dict) or raw.get("planner") != "adam":
            return None
        try:
            return cls.model_validate(raw)
        except ValueError:
            return None
