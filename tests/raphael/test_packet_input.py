"""Raphael on the scene packet (plan/2026-11-11): the whole packet reaches the model, and Raphael's own code (tools,
checks, clock) runs on the `SceneS` built from it. No model, no database.

The fixtures are two Ekama packets assembled by `lab/two_memories` (S02: a voice message and a phone call;
S08: the mill)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from contracts.raphael import packet as rp
from contracts.raphael.scene import Brief, heard_names, is_heard
from contracts.raphael.tools import Stage1Session

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "raphael"

# Left out ON PURPOSE (anything else in the packet must reach the model word for word): the reason an empty field is
# empty, the neighbour's other end (the scene before is shown by how it ENDS, the one after by how it OPENS), the
# lookup tables (`ids`, a section's own id and kind), the rule's topic word (its text is shown), and the summary a card
# reads from a range too wide to trust (`summary.empty`).
LEFT_OUT = (
    r"\.empty$",
    r"before_in_story\.(opens_with|people_at_end)",
    r"after_in_story\.(ends_with|people_at_end)",
    r"^\.ids\.",
    r"^\.C_place\.(id|kind)$",
    r"^\.G_direction\[\d+\]\.about$",
)


def _packet(name: str) -> dict:
    return json.loads((FIX / f"packet_ekama_{name}.json").read_text(encoding="utf-8"))


def _leaves(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _leaves(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _leaves(v, f"{path}[{i}]")
    elif isinstance(x, str) and len(x.strip()) > 2:
        yield path, x


@pytest.mark.parametrize("name", ["s02", "s08"])
def test_nothing_in_the_packet_is_lost(name):
    p = _packet(name)
    text, _, _ = rp.opening(p)
    flat = " ".join(text.split())
    lost = [
        (k, v) for k, v in _leaves(p) if " ".join(v.split()) not in flat and not any(re.search(r, k) for r in LEFT_OUT)
    ]
    assert lost == []


def test_who_is_heard_comes_from_the_packet_not_from_word_lists():
    text, scene, _ = rp.opening(_packet("s02"))
    assert heard_names(scene) == ["Aruni", "Mudalali"]  # today's path catches Aruni only; Mudalali's call was lost
    assert all(is_heard(b) for b in scene.lines)
    assert "<voice_only>\nAruni, Mudalali: heard and never seen" in text


def test_raphaels_own_session_runs_on_the_packet_scene():
    _, scene, ids = rp.opening(_packet("s08"))
    assert len(scene.blocks) == 10 and [b.line_id for b in scene.lines] == ["L2", "L3", "L8"]
    assert ids["b4"] == "E01-S08-B05" and ids["L8"] == "E01-S08-B09"
    assert "Nimal" not in scene.cast and scene.codes["C01"] == "Dinu"
    report = Stage1Session(Brief(scene, float(scene.envelope_s or 0)), max_turns=20, scene_no="8").report()
    assert "Block b9 has no must clip" in report and "Line L8 is carried by no must clip" in report
    assert "target 180 s, cap 270 s" in report


def test_the_clock_reads_the_packets_events():
    _, scene, _ = rp.opening(_packet("s08"))
    last = scene.blocks[-1]  # the gun, the kick and the arrests: four events, not one beat
    assert last.events == 4 and "Mudalali" in last.now


def test_the_agent_input_comes_from_the_packet():
    from hiru_ai.agents.raphael.raphael_planner.agent import input_from_packet, user_message

    inp, _ids = input_from_packet(_packet("s08"), scene_no="8")
    assert user_message(inp).startswith("<packet>\nSCENE E01-S08") and inp.guide_s == 180.0 and inp.breakdown is None
    assert "<production>" not in inp.opening and "<script>" not in inp.opening
