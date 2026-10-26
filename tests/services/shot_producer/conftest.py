from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "shot_producer"))

from tests.services.fakes import FakeLLM  # noqa: E402
from tests.services.production_fixture import CANON, HOUSE, KAMALA, NIMAL, PID, fixture_scene  # noqa: E402, F401


class FakeStore:
    """shot_producer's Store, in memory."""

    def __init__(self, scene: dict, lines: list[dict], shots: list[dict], *, canon: list[dict] | None = None,
                 orientation: str = "horizontal") -> None:
        self.scene_row, self.line_rows = scene, lines
        self.shot_rows = {s["id"]: s for s in shots}
        self.canon_rows = canon if canon is not None else CANON
        self.orientation = orientation
        self.frames: dict[str, dict] = {}
        self.prompts: list[dict] = []
        self.audits: list[dict] = []
        self.technique_queries: list[str] = []

    def production(self, production_id: UUID) -> dict | None:
        return {"id": str(production_id), "title": "Harbour Lights", "orientation": self.orientation,
                "settings": {}, "summary": ""}

    def scenes(self, production_id: UUID, scene_ids: list[str]) -> list[dict]:
        return [self.scene_row] if self.scene_row["id"] in scene_ids else []

    def shots(self, scene_id: str) -> list[dict]:
        return sorted((dict(s) for s in self.shot_rows.values()), key=lambda s: s["number"])

    def shot_scenes(self, production_id: UUID, shot_ids: list[str]) -> list[str]:
        return [self.scene_row["id"]] if any(s in self.shot_rows for s in shot_ids) else []

    def lines(self, scene_id: str) -> list[dict]:
        return self.line_rows

    def canon(self, production_id: UUID) -> list[dict]:
        return self.canon_rows

    def lead_persona(self, production_id: UUID) -> dict | None:
        return {"id": str(uuid4()), "name": "Grounded Realist", "specialty": "",
                "style_note": "Available light, held frames.", "charter": "Hold on reactions rather than cutting away."}

    def accepted_frames(self, shot_ids: list[str]) -> dict[str, dict]:
        return {k: v for k, v in self.frames.items() if k in shot_ids}

    def last_prompt_version(self, shot_id: str) -> int:
        return max((p["version"] for p in self.prompts if p["shot_id"] == shot_id), default=0)

    def techniques(self, query: str, embedding: list[float] | None, k: int = 4) -> list[dict]:
        self.technique_queries.append(query)
        return [{"name": "Push in", "abbreviation": "", "use_case": "Build tension",
                 "definition": "The camera moves slowly toward the subject."}]

    def save_design(self, shot_id: str, ir: dict, design: dict) -> None:
        self.shot_rows[shot_id] = {**self.shot_rows[shot_id], "ir": ir, "design": design}

    def add_prompt(self, row: dict) -> None:
        self.prompts.append(row)
        self.shot_rows[row["shot_id"]]["status"] = "prompt"

    def audit(self, row: dict) -> None:
        self.audits.append(row)


class ProducerLLM(FakeLLM):
    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]


def dp_answer(numbers: list[int], *, movement: str = "Dolly in") -> dict[str, Any]:
    """A model's scene answer for these shot numbers."""
    return {"shots": [{
        "number": n, "setting": "A smoky dawn kitchen in C01's house",
        "cinematography": {"camera": "dolly, 50mm, f/2.8", "angle": "eye level", "framing": "a tight single on C02",
                           "movement": "slow push in", "white_balance": "warm 3200K", "color_tone": "warm, film-like",
                           "depth_of_field": "Shallow", "lens_artifacts": "none"},
        "lighting": "Firelight from the left, deep shadows.",
        "subjects": [{"id": "C01", "description": "C01 at the stove", "action": "stirs the pan"},
                     {"id": "C09", "description": "a neighbour", "action": "passes the window"}],
        "beats": [{"time": "0-3s", "camera": "medium", "director_line": "C02 waits in the doorway.",
                   "action": "He says අම්මේ softly"},
                  {"time": "3-6s", "camera": "push arrives", "director_line": "She keeps stirring.",
                   "action": "stirs"}],
        "audio": "fire crackle, radio news",
        "first_frame": {"composition": "C01 at the stove, back to the door", "subjects": ["C01"],
                        "setting": "kitchen", "lighting": "firelight"},
        "recommendation": {"angle": "Eye level", "lens": "50mm", "aperture": "f/2.8", "movement": movement,
                           "speed": "None", "axis": "Side A · left to right", "lighting": "Night, lamp key"},
        "rationale": "A slow push builds the hesitation.",
    } for n in numbers]}


@pytest.fixture
def scene0() -> tuple[dict, list[dict], list[dict]]:
    return fixture_scene(0)
