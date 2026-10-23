"""The live structure build (screen 0b): its stages, its agents, and the questions it asks.

A build is ONE job that runs three functions in turn (`BUILD_PIPELINE`). Each publishes
`stage` events as it starts and finishes a stage, and `progress` / `agent_step` events naming
the agent at work, so the screen can draw the stage list and the agent strip from `job_events`
alone. When the material is ambiguous the build asks a person (`questions`) and waits; the last
answer resumes it where it stopped.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.jobs import JobKind

BUILD_PIPELINE: tuple[JobKind, ...] = (JobKind.CANON_EXTRACT, JobKind.STRUCTURE_BUILD, JobKind.SCRIPT_SPLIT)


class Stage(StrEnum):
    READ = "read"  # read the documents
    CANON = "canon"  # extract canon
    EPISODES = "episodes"  # split episodes
    SCENES = "scenes"  # split scenes
    SHOTS = "shots"  # plan shots
    CONTINUITY = "continuity"  # continuity check
    REVIEW = "review"  # a person reviews


STAGE_LABEL: dict[Stage, str] = {
    Stage.READ: "Read documents",
    Stage.CANON: "Extract canon",
    Stage.EPISODES: "Split episodes",
    Stage.SCENES: "Split scenes",
    Stage.SHOTS: "Plan shots",
    Stage.CONTINUITY: "Continuity check",
    Stage.REVIEW: "Your review",
}


class Agent(StrEnum):
    """Agent names as job events carry them; the UI shows `AGENT_LABEL`."""

    INGESTION = "ingestion"
    CANON = "canon_extractor"
    ARCHITECT = "script_architect"
    PLANNER = "shot_planner"
    CONTINUITY = "continuity_checker"


AGENT_LABEL: dict[Agent, str] = {
    Agent.INGESTION: "Ingestion agent",
    Agent.CANON: "Canon extractor",
    Agent.ARCHITECT: "Script Architect",
    Agent.PLANNER: "Shot Planner",
    Agent.CONTINUITY: "Continuity Checker",
}


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    # No durable checkpointer was configured, so the build could not wait: it took the
    # suggested answer and recorded the question so a person can still review the choice.
    DEFAULTED = "defaulted"


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)


class Question(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    production_id: UUID
    job_id: UUID | None
    agent: str
    scope: str  # "Ep 03 Scene 6"
    title: str
    body: str
    # The first option is the suggested one (the UI draws it as the primary action).
    options: list[QuestionOption]
    allow_text: bool = False  # a free-text answer is accepted as well as the options
    status: QuestionStatus
    answer: dict[str, Any] | None = None
    answered_by: UUID | None = None
    answered_at: datetime | None = None
    created_at: datetime


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(default=None, max_length=120)  # one of the options
    text: str | None = Field(default=None, max_length=2000)  # free text, when allowed

    @model_validator(mode="after")
    def _one(self) -> AnswerRequest:
        if not (self.value or self.text):
            raise ValueError("send an option value or a text answer")
        return self
