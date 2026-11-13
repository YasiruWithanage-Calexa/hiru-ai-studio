"""Arm T: TODAY's Sable, its real code unchanged, on the Zora lab's scene (Hiru Short Combined 2, Scene 03, Raphael).

The production's stores are the repo's test fakes, filled from `lab/zora_rows/input/<scene>.json`: nothing reads or
writes a database. The models are real (Sable's tiers: `sable` gpt-5-mini low, `sable_deep` gpt-5 medium; the thread
summary on `low`). Every model call is entered in `runs/ledger.csv` from the usage rows Sable's middleware reports.

Money: Sable has no dollar cap of its own (only call counts: 10 model calls, 8 tool calls), so the lab refuses a TURN
before it starts when the lab's spend plus `TURN_WORST_USD` would pass `LAB_CAP_USD`.
"""

from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Any

from contracts.sable.events import SableTurnPayload
from hiru_ai.core.context import Ports, RunContext
from hiru_ai.core.fakes import FakeCanon, FakeChat, FakeScenes, FakeSearch, FakeStaging, FakeStructure

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
LEDGER = RUNS / "ledger.csv"
LAB_CAP_USD = 1.00
TURN_WORST_USD = 0.30  # 10 model calls on gpt-5 medium with a growing thread: refuse a turn that could pass the cap
PRICES = {"gpt-5-nano": (0.05, 0.005, 0.40), "gpt-5-mini": (0.25, 0.025, 2.00), "gpt-5": (1.25, 0.125, 10.00),
          "gpt-6.1-terra": (1.00, 0.05, 5.00), "gpt-6.1-sol": (2.00, 0.10, 10.00)}
FIELDS = ["time", "run", "arm", "slot", "model", "effort", "input_tokens", "cached_tokens", "output_tokens", "dollars",
          "status"]
SCENE_FILE = HERE.parent / "zora_rows" / "input" / "0f4ba0fd-db0b-4722-8feb-e89586b06f24.json"

Row = dict[str, Any]


class CapError(Exception):
    pass


def spent() -> float:
    if not LEDGER.exists():
        return 0.0
    with LEDGER.open(encoding="utf-8", newline="") as f:
        return sum(float(r["dollars"] or 0) for r in csv.DictReader(f))


def enter(row: Row) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    fresh = not LEDGER.exists()
    with LEDGER.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def price(model: str, inp: int, cached: int, out: int) -> float:
    key = next((k for k in sorted(PRICES, key=len, reverse=True) if model.startswith(k)), "")
    if not key:
        return 0.0
    p = PRICES[key]
    return (inp - cached) * p[0] / 1e6 + cached * p[1] / 1e6 + out * p[2] / 1e6


def load_scene() -> Row:
    return json.loads(SCENE_FILE.read_text(encoding="utf-8"))


@dataclass
class TodaySable:
    """One thread of today's Sable over the lab scene; the fakes persist between turns, as a real thread does."""

    run: str
    data: Row = field(default_factory=load_scene)
    calls: list[Row] = field(default_factory=list)
    production: Row | None = None  # the whole production (the lab story copy of "test"): every scene in the fakes
    open_ref: str = ""  # the scene in view with `production`, like "E2S2"

    def __post_init__(self) -> None:
        if self.production is not None:
            self._whole_production()
            return
        d = self.data
        scene = dict(d["scene"])
        self.production_id = str(d["production"]["id"])
        self.scene_id = str(scene["id"])
        episode = {"id": str(scene["episode_id"]), "production_id": self.production_id, "number": 1, "title": "Episode 1"}
        scene["episode"] = {"number": 1, "id": episode["id"]}
        production = {**d["production"], "id": self.production_id}
        canon = [{**c, "production_id": self.production_id, "kind": "character"} for c in d["characters"]]
        self.thread_id = str(uuid.uuid4())
        self.chat = FakeChat(threads=[{"id": self.thread_id, "production_id": self.production_id,
                                       "title": "Sable", "summary": "", "summarised": 0}])
        self.ports = Ports(scenes=FakeScenes(production=production, scenes=[scene], lines=d["lines"], shots=d["shots"],
                                             canon=canon),
                           canon=FakeCanon(entities=canon), chat=self.chat, staging=FakeStaging(),
                           search=FakeSearch(), structure=FakeStructure(episodes=[episode], scenes=[scene]))

    def _whole_production(self) -> None:
        """Every scene, shot, line, episode and canon card of the production in the fakes; the scene in view is
        `open_ref`. Today's Sable reads all of it through its tools, as it does in the product."""
        p = self.production or {}
        self.production_id = str(p["production"]["id"])
        numbers = {e["id"]: int(e["number"]) for e in p["episodes"]}
        episodes = [{**e, "id": str(e["id"]), "production_id": self.production_id} for e in p["episodes"]]
        scenes = []
        for s in p["scenes"]:
            row = dict(s)
            row["episode"] = {"number": numbers[s["episode_id"]], "id": str(s["episode_id"])}
            scenes.append(row)
        ep, n = (int(x) for x in self.open_ref.upper().lstrip("E").split("S"))
        self.scene_id = str(next(s["id"] for s in scenes if s["episode"]["number"] == ep and int(s["number"]) == n))
        canon = [{**c, "production_id": self.production_id, "summary": (c.get("card") or {}).get("summary", "")}
                 for c in p["canon"]]
        production = {**p["production"], "id": self.production_id}
        self.thread_id = str(uuid.uuid4())
        self.chat = FakeChat(threads=[{"id": self.thread_id, "production_id": self.production_id,
                                       "title": "Sable", "summary": "", "summarised": 0}])
        self.ports = Ports(scenes=FakeScenes(production=production, scenes=scenes, lines=p["lines"], shots=p["shots"],
                                             canon=canon),
                           canon=FakeCanon(entities=canon), chat=self.chat, staging=FakeStaging(),
                           search=FakeSearch(), structure=FakeStructure(episodes=episodes, scenes=scenes))

    def _sink(self, slot: str):
        def collect(usage: Row) -> None:
            model = str(usage.get("model") or "")
            i, c, o = (int(usage.get(k) or 0) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
            dollars = price(model, i, c, o)
            row = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "run": self.run, "arm": "today", "slot": slot,
                   "model": model, "effort": str(usage.get("phase") or ""), "input_tokens": i, "cached_tokens": c,
                   "output_tokens": o, "dollars": f"{dollars:.5f}", "status": "done"}
            enter(row)
            self.calls.append({"slot": slot, "phase": usage.get("phase"), "model": model, "input_tokens": i,
                               "cached_tokens": c, "output_tokens": o, "dollars": round(dollars, 5)})
        return collect

    def turn(self, slot: str, message: str) -> Row:
        if spent() + TURN_WORST_USD > LAB_CAP_USD + 1e-9:
            raise CapError(f"Refused before the turn: ${spent():.4f} spent, a turn could cost ${TURN_WORST_USD:.2f}, "
                           f"the lab cap is ${LAB_CAP_USD:.2f}.")
        from cinematic.run import load_env  # the .env with the key (the lab's one place for it)
        from hiru_ai.core.settings import get_settings
        from hiru_ai.systems.sable.sable_chat import graph

        load_env()  # setdefault: a blank OPENAI__API_KEY in the environment wins (the `wire` check runs with no model)
        get_settings.cache_clear()
        user_id = str(uuid.uuid4())
        self.chat.add_message({"id": user_id, "thread_id": self.thread_id, "production_id": self.production_id,
                               "kind": "user", "speaker": "Director", "text": message, "blocks": []})
        req = SableTurnPayload(production_id=self.production_id, thread_id=self.thread_id, actor_user_id=uuid.uuid4(),
                               actor_name="Director", role="director", can_stage=True, message=message,
                               user_message_id=user_id, scene_id=self.scene_id)
        # a fresh card store each turn, as each product turn has (run 1: one shared store showed turn 3's card on every
        # later turn; a lab artifact, not Sable's)
        self.ports = dc_replace(self.ports, staging=FakeStaging())
        ctx = RunContext(production_id=uuid.UUID(self.production_id), ports=self.ports, usage_sink=self._sink(slot))
        before = len(self.calls)
        started = time.time()
        statuses, error = [], ""
        for event, data in graph.run(req, ctx):
            if event == "status":
                statuses.append(str(data.get("text") or ""))
            elif event == "error":
                error = str(data.get("message") or data)
        last = next((m for m in reversed(self.chat.message_rows) if m.get("kind") != "user"), {})
        blocks = last.get("blocks") or []
        text = " ".join(str(b.get("text") or "") for b in blocks if b.get("kind") == "text").strip()
        cards = [b for b in blocks if b.get("kind") not in ("text", "used")]
        calls = self.calls[before:]
        return {"slot": slot, "message": message, "reply": text, "cards": cards, "statuses": statuses, "error": error,
                "calls": calls, "dollars": round(sum(c["dollars"] for c in calls), 5),
                "seconds": round(time.time() - started, 1)}
