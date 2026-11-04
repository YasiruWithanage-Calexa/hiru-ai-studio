"""The gold set (tests/eval/adam/): scenes, the masters written for them and the classic baseline plans.

A scene is a SceneScript; a master is an AdamPlan in the card format of plan/2026-11-04b §5.1; a baseline is what
`script_split` stores as `shots` rows, which `baseline_plan` lays onto the same scene (one SCRIPT moment per block, one
card per shot, every line on its speaker) so that the same code can score both against the same yardstick.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from contracts.adam.plan import norm
from contracts.timing import action_seconds

GOLD = Path(__file__).resolve().parents[1] / "eval" / "adam"
FRAMING_TO_CARD = {"WIDE": ("WS", "single"), "MS": ("MS", "single"), "MCU": ("MCU", "single"),
                   "CU": ("CU", "single"), "TWO": ("MWS", "two"), "OTS": ("MS", "ots"), "INSERT": ("INSERT", "single")}


def _load(kind: str, name: str) -> dict[str, Any]:
    data = yaml.safe_load((GOLD / kind / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def names() -> list[str]:
    return sorted(p.stem for p in (GOLD / "masters").glob("*.yaml"))


def scene(name: str) -> dict[str, Any]:
    """The SceneScript payload of a gold scene."""
    return dict(_load("scenes", name)["scene"])


def master(name: str) -> dict[str, Any]:
    """The master's AdamPlan payload."""
    return dict(_load("masters", name)["plan"])


def baseline_shots(name: str) -> list[dict[str, Any]]:
    return list(_load("baselines", name)["shots"])


def baseline_plan(name: str) -> dict[str, Any]:
    """The classic plan as an AdamPlan: the master's analysis and treatment (the yardstick), the classic cards."""
    sc, plan = scene(name), master(name)
    cast = sc["cast"]
    blocks = {b["index"]: b for b in sc["blocks"]}
    moments: list[dict[str, Any]] = []
    for i in sorted(blocks):
        b = blocks[i]
        line = b["kind"] == "dialogue"
        moments.append({
            "id": f"c{i}", "tier": "script", "serves": [f"b{i}"],
            "who": [b["speaker"]] if line and norm(b["speaker"]) in {norm(c) for c in cast} else list(cast),
            "lines": [b["line_id"]] if line else [], "seen": b["text"] if not line else "",
            "seconds_need": 0.0 if line else action_seconds("act")})
    cards = []
    for shot in baseline_shots(name):
        size, arrangement = FRAMING_TO_CARD[shot["framing"]]
        span = range(shot["block_start"], shot["block_end"])
        in_span = [blocks[i] for i in span if i in blocks]
        speakers = [b["speaker"] for b in in_span if b["kind"] == "dialogue"]
        subject = speakers[0] if speakers and norm(speakers[0]) in {norm(c) for c in cast} else cast[0]
        cards.append({
            "number": shot["number"], "title": shot["title"], "moments": [f"c{i}" for i in span if i in blocks],
            "size": size, "arrangement": arrangement, "subject": subject, "take_s": shot["duration_s"],
            "lines": [{"line_id": b["line_id"], "on_speaker": True} for b in in_span if b["kind"] == "dialogue"],
            "cut_in": {"link": "cut", "motive": "line" if speakers else "action"}})
    return {"analysis": plan["analysis"], "treatment": plan["treatment"], "moments": moments, "cards": cards,
            "staging": {}, "sound_map": {}}
