"""Track B of plan/2026-11-12c: a scene's props by canon id when it has a breakdown, and whole words otherwise ("photo"
no longer matches "photographs", which put the dashboard photo in the garage scene); the packet's canon by id."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.breakdown import packet
from contracts.breakdown.schema import Breakdown
from contracts.canon import named_in, props_in
from contracts.canon_refine import canon_map

F = Path(__file__).resolve().parents[1] / "fixtures" / "canon_refine"
PROPS = [{"id": "p1", "name": "photo"}, {"id": "p2", "name": "key"}, {"id": "p3", "name": "red thread"}]


def test_a_name_is_matched_as_whole_words() -> None:
    assert named_in("photo", "She looks at the photo.") and named_in("Red Thread", "a red thread on his wrist")
    assert not named_in("photo", "Photographs cover the wall.") and not named_in("key", "a monkey on the roof")
    assert not named_in("", "anything")


def test_props_by_id_win_over_names() -> None:
    text = "Photographs on the wall; he turns the key."
    assert props_in(PROPS, text) == ["key"]
    assert props_in(PROPS, text, ids=["p1", "p3"]) == ["photo", "red thread"]
    assert props_in(PROPS, text, ids=[]) == []  # a breakdown that gives the scene no things


def test_the_packet_carries_the_scene_s_canon_by_id() -> None:
    fx = json.loads((F / "ekama.json").read_text(encoding="utf-8"))
    bd = Breakdown.model_validate(fx["memory"])
    assert packet.canon_of(bd, "E01-S01") == {}  # no map yet
    bd.canon_ids = canon_map(bd, fx["canon"])
    got = packet.canon_of(bd, "E01-S01")
    ids = {c["code"]: c["id"] for c in fx["canon"]}
    assert got["place"] == ids["L03"]
    assert ids["C03"] in got["people"]  # Nimal is a body on screen: in the picture, though he never speaks
    assert ids["P02"] in got["things"]  # the key (hero)
