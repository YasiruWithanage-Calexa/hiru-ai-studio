"""Typed seams of the zora_reply agent (plan/2026-11-06e §3 REPLY)."""
from __future__ import annotations

from pydantic import BaseModel


class Input(BaseModel):
    persona: str = ""  # "You are <the lead>: <their style>"; empty = no persona (D6: the persona is the voice)
    transcript: list[str] = []  # "speaker: text", oldest first
    plan: str  # the plain rendering, scoped to what the turn touched (`contracts.zora.render.consumer`)
    message: str  # what the person just wrote
    turn: list[str]  # the ledger's blocks (`Ledger.context()`) and any lane fact: the LAST thing the model reads


class Output(BaseModel):
    text: str
