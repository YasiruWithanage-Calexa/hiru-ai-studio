"""What `scenes.raphael` holds (plan/2026-11-08e §7 phase 4): Raphael's result for one scene, as JSON.

The intended cut, the shoot bin (stage 1's must clips and stage 2's cinematic clips, each with its design), the editor
notes and blend notes, the moment review, what is left reported, the length cap used and the seconds against it, and a
hash of what Raphael was given (a re-plan whose hash is unchanged makes no call).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from contracts.raphael.wire import DEFAULT_CAP, BreakdownW, Clip, EditPlanW, LengthCap, ReviewRow

STORED_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Left(_Model):
    """A report that was left (never a blocking fault: `finish` refuses those)."""

    code: str
    sentence: str
    clips: list[str] = []
    fix: Literal["repair", "report"] = "report"
    key: str = ""  # the check's key ("state:handover:c05:phone:9", plan/2026-11-09): what kind of report it is


class Seconds(_Model):
    """The seconds of takes against the target and the cap (never money)."""

    target_s: float = 0.0  # the scene's given length
    cap_s: float = 0.0  # the given length x the length cap used
    take_s: int = 0
    must_s: int = 0
    cinematic_s: int = 0


class StoredRaphael(_Model):
    version: int = STORED_VERSION
    planner: Literal["raphael"] = "raphael"
    job_id: str = ""
    input_hash: str = ""  # what Raphael was given; "" = unknown
    # stage 1 finished and stage 2 finished: a stage that was stopped (turns, the run cap, an error) is marked here and
    # whatever passed the checks is still saved (D1)
    stage1: Literal["finished", "stopped", "none"] = "none"
    stage2: Literal["finished", "stopped", "skipped", "none"] = "none"
    stopped: str = ""  # why a stage stopped early, in a sentence a person reads
    cap: LengthCap = DEFAULT_CAP  # the length cap used for this result (§2.1)
    # plan/2026-11-10: the director's breakdown stage 1 built from; optional: STORED_VERSION stays 1, no schema change
    breakdown: BreakdownW | None = None
    edit: EditPlanW | None = None
    clips: list[Clip] = []
    line_ids: dict[str, str] = {}  # the agent-facing id (L4) → the dialogue line's id
    editor_notes: list[str] = []  # stage 1's
    blend_notes: list[str] = []  # stage 2's: one per cinematic clip, starting with its id
    review: list[ReviewRow] = []  # stage 2's: every moment once, earns yes or no, and why
    seconds: Seconds = Seconds()
    left: list[Left] = []  # reports that remain (a line too long for its take, a Veo caution ...)
    report: dict[str, Any] = Field(default_factory=dict)  # turns, calls, per-stage outcome: never money
    # The shot list that was on the scene when Raphael first planned it, kept for a side-by-side look.
    previous: dict[str, Any] = Field(default_factory=dict)

    def data(self) -> dict[str, Any]:
        """The JSON `scenes.raphael` holds."""
        return dict(self.model_dump(mode="json"))

    @classmethod
    def load(cls, raw: Any) -> StoredRaphael | None:
        """The stored result of a scene row's `raphael` column; None when Raphael never planned the scene (the column is
        `{}`) or holds something this version cannot read."""
        if not isinstance(raw, dict) or raw.get("planner") != "raphael":
            return None
        try:
            return cls.model_validate(raw)
        except ValueError:
            return None

    def musts(self) -> list[Clip]:
        return [c for c in self.clips if not c.is_extra]

    def extras(self) -> list[Clip]:
        return [c for c in self.clips if c.is_extra]
