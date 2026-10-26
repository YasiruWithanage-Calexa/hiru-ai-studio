from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "services" / "director_chat"))

from contracts import sceneplan  # noqa: E402
from contracts.screenplay import parse_document  # noqa: E402
from contracts.shotplan import ProposedShot, fit  # noqa: E402
from tests.services.doc_ingest.conftest import CORPUS  # noqa: E402
from tests.services.fakes import FakeLLM  # noqa: E402

PID = uuid4()
NIMAL, KAMALA, PAN = str(uuid4()), str(uuid4()), str(uuid4())


def fixture_scene(n: int = 0, *, envelope_s: int = 60, per_block: bool = True) -> tuple[dict, list[dict], list[dict]]:
    """A scene from the Harbour Lights fixture → (scene row, line rows, shot rows). Shots are
    one per block (`per_block`) or one for the whole scene, fitted by the real kernel."""
    doc = parse_document((CORPUS / "harbour-lights-ep01-script.fountain").read_text(encoding="utf-8"))
    parsed = doc.scenes[n]
    scene_id = str(uuid4())
    blocks, lines = [], []
    for b in parsed.blocks:
        if b.kind == "dialogue":
            lid = str(uuid4())
            lines.append({"id": lid, "production_id": str(PID), "scene_id": scene_id, "ord": len(lines),
                          "speaker": b.speaker.title(), "text": b.text, "delivery": b.delivery,
                          "character_id": {"NIMAL": NIMAL, "KAMALA": KAMALA}.get(b.speaker)})
            blocks.append({"kind": "dialogue", "text": "", "line_id": lid})
        else:
            blocks.append({"kind": b.kind, "text": b.text, "line_id": None})
    scene = {"id": scene_id, "production_id": str(PID), "episode_id": str(uuid4()), "number": n + 1,
             "heading": parsed.heading.raw, "envelope_s": envelope_s, "status": "split", "script": blocks,
             "location_id": str(uuid4())}
    items = sceneplan.items_for(blocks, lines)
    proposal = ([ProposedShot(i, i + 1, "MS") for i in range(len(items))] if per_block
                else [ProposedShot(0, len(items), "WIDE")])
    result = fit(items, proposal, envelope_s=envelope_s)
    shots, line_rows, _ = sceneplan.rows_after_fit(scene, [{"start": p.start} for p in proposal], result, lines)
    return scene, line_rows, shots


class FakeStore:
    """director_chat's Store, in memory."""

    def __init__(self, scene: dict, lines: list[dict], shots: list[dict], *, settings: dict | None = None,
                 board: list[dict] | None = None) -> None:
        self.scene_row, self.line_rows, self.shot_rows = scene, lines, shots
        self.settings = settings or {}
        self.board_rows = board or []
        self.saved: list[dict[str, Any]] = []
        self.message_rows: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.memory_rows: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []

    def production(self, production_id: UUID) -> dict | None:
        return {"id": str(production_id), "title": "Harbour Lights", "orientation": "horizontal",
                "settings": self.settings, "summary": ""}

    def scene(self, production_id: UUID, scene_id: UUID) -> dict | None:
        ok = str(production_id) == self.scene_row["production_id"] and str(scene_id) == self.scene_row["id"]
        return self.scene_row if ok else None

    def lines(self, scene_id: UUID) -> list[dict]:
        return self.line_rows

    def shots(self, scene_id: UUID) -> list[dict]:
        return sorted(self.shot_rows, key=lambda s: s["number"])

    def canon(self, production_id: UUID) -> list[dict]:
        return [{"id": KAMALA, "kind": "character", "code": "C01", "name": "Kamala", "aliases": ["Amma"],
                 "locked": True, "current": {"card": {"age": 52}, "wardrobe_anchor": "faded blue cotton saree",
                                             "voice_pin": "low, clipped female voice"}},
                {"id": NIMAL, "kind": "character", "code": "C02", "name": "Nimal", "aliases": [], "locked": False,
                 "current": None},
                {"id": self.scene_row["location_id"], "kind": "location", "code": "L01", "name": "Harbour kitchen",
                 "aliases": [], "locked": True, "current": None},
                {"id": PAN, "kind": "prop", "code": "P01", "name": "Brass pan", "aliases": [], "locked": False,
                 "current": None}]

    def board(self, production_id: UUID) -> list[dict]:
        return self.board_rows

    def default_persona(self) -> dict | None:
        return {"id": str(uuid4()), "name": "Classic Teledrama", "initials": "CT", "specialty": "",
                "style_note": "Clear coverage.", "charter": "Cover every speaker clearly."}

    def messages(self, thread_id: UUID, limit: int = 12) -> list[dict]:
        return self.history[-limit:]

    def memory(self, production_id: UUID, limit: int = 20) -> list[dict]:
        return [{"kind": m["kind"], "text": m["text"]} for m in self.memory_rows][:limit]

    def open_questions(self, production_id: UUID) -> list[dict]:
        return [{"scope": "Ep 01 Scene 2", "title": "Place", "body": "Is the breakwater L02?"}]

    def ready_documents(self, production_id: UUID) -> list[dict]:
        return [{"id": "d1", "filename": "bible.md"}]

    def search(self, *, query: str, embedding: list[float] | None, production_id: UUID, document_ids: list[str],
               k: int = 6) -> list[dict]:
        self.searches.append({"query": query, "production_id": str(production_id), "document_ids": document_ids})
        return [{"id": str(uuid4()), "document_id": "d1", "heading": "Kamala", "content": "Kamala is 52."}]

    def save_plan(self, scene_id: UUID, shots: list[dict], removed: list[str], lines: list[dict],
                  scene_fields: dict, removed_lines: list[str] | None = None) -> None:
        self.saved.append({"shots": shots, "removed": removed, "lines": lines, "scene": scene_fields,
                           "removed_lines": removed_lines or []})
        keep = {s["id"] for s in shots}
        self.shot_rows = [s for s in self.shot_rows if s["id"] not in removed and s["id"] not in keep] + shots
        self.line_rows = lines
        self.scene_row = {**self.scene_row, **scene_fields}

    def add_message(self, row: dict) -> None:
        self.message_rows.append(row)

    def audit(self, row: dict) -> None:
        self.audits.append(row)

    def add_memory(self, item: dict, embedding: list[float] | None, model: str) -> None:
        self.memory_rows.append({**item, "embedding": embedding})


def tool_call(name: str, arguments: str = "{}") -> Any:
    return SimpleNamespace(id=f"call_{name}", function=SimpleNamespace(name=name, arguments=arguments))


class DirectorLLM(FakeLLM):
    """FakeLLM plus the calls only the director makes: tool rounds, streamed text, embeddings."""

    def __init__(self, responders: dict[str, Callable[[str, str], dict]] | None = None, *, enabled: bool = True,
                 tool_script: list[Any] | None = None, reply: str = "Done. S02 now holds on Nimal.") -> None:
        super().__init__(responders, enabled=enabled)
        self.tool_script = list(tool_script or [])  # assistant messages, in order
        self.reply = reply
        self.streamed: list[list[dict]] = []
        self.tool_rounds: list[list[dict]] = []

    def tool_round(self, *, tier: str, phase: str, messages: list[dict], tools: list[dict]) -> Any:
        self.tool_rounds.append([dict(m) for m in messages])
        self.calls.append({"tier": tier, "phase": phase, "schema": "tools", "system": messages[0]["content"],
                           "user": messages[1]["content"]})
        if self.tool_script:
            return self.tool_script.pop(0)
        return SimpleNamespace(content=self.reply, tool_calls=None)

    def stream(self, *, tier: str, phase: str, messages: list[dict]) -> Iterator[str]:
        self.streamed.append(messages)
        self.calls.append({"tier": tier, "phase": phase, "schema": "stream", "system": messages[0]["content"],
                           "user": messages[1]["content"]})
        yield from (self.reply[:10], self.reply[10:])

    def embed(self, texts: list[str], *, phase: str) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]


@pytest.fixture
def scene0() -> tuple[dict, list[dict], list[dict]]:
    return fixture_scene(0)
