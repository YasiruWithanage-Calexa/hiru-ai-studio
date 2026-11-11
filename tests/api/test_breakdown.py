"""The scene packet, read-only, and the one-scene refresh (plan/2026-11-11 phases 5 and 6). No network, no database."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tests.api.conftest import World
from tests.api.test_scenes import seed_scene

PACKET = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "raphael" / "packet_ekama_s02.json").read_text(encoding="utf-8")
)


def _url(world: World, scene_id: str, tail: str = "packet") -> str:
    return f"/v1/productions/{world.production}/scenes/{scene_id}/{tail}"


def _with_packet(world: World, *, version: int = 1, waits: list[str] | None = None) -> str:
    s = seed_scene(world)
    sid = s["scene"]["id"]
    world.repos.packets.rows[sid] = {
        "scene_id": sid,
        "production_id": str(world.production),  # type: ignore[attr-defined]
        "scene_key": "E01-S02",
        "packet": PACKET,
        "waits": waits or [],
        "script_version": version,
    }
    return sid


def test_every_member_reads_the_packet_and_it_holds_no_money(world: World):
    sid = _with_packet(world)
    for who in (world.producer, world.writer, world.crew, world.reviewer):
        r = world.client.get(_url(world, sid), headers=world.headers(who))
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["ready"] and not got["stale"] and got["scene_key"] == "E01-S02"
        assert got["packet"]["A_scene"]["id"] == "E01-S02"
    text = json.dumps(got).lower()
    assert "$" not in text and "cost" not in text and "usd" not in text and "gpt" not in text


def test_a_stranger_gets_404(world: World):
    sid = _with_packet(world)
    assert world.client.get(_url(world, sid), headers=world.headers(world.outsider)).status_code == 404


def test_a_packet_made_for_an_older_script_is_stale(world: World):
    sid = _with_packet(world, version=0)
    got = world.client.get(_url(world, sid), headers=world.headers(world.writer)).json()
    assert got["stale"] and not got["ready"]


def test_a_packet_that_waits_says_why(world: World):
    sid = _with_packet(world, waits=["blocking finding: 1 word(s) in no block"])
    got = world.client.get(_url(world, sid), headers=world.headers(world.writer)).json()
    assert got["waits"] == ["blocking finding: 1 word(s) in no block"] and not got["ready"]


def test_a_scene_without_a_breakdown_is_404_with_a_sentence(world: World):
    s = seed_scene(world)
    r = world.client.get(_url(world, s["scene"]["id"]), headers=world.headers(world.writer))
    assert r.status_code == 404 and "no breakdown" in r.json()["detail"]
    assert world.client.get(_url(world, str(uuid4())), headers=world.headers(world.writer)).status_code == 404


def test_the_refresh_starts_a_structure_job_on_that_scene(world: World):
    sid = _with_packet(world)
    r = world.client.post(_url(world, sid, "breakdown/refresh"), headers=world.headers(world.writer))
    assert r.status_code == 202, r.text
    job = world.repos.jobs.rows[r.json()["job_id"]]  # type: ignore[attr-defined]
    assert job["kind"] == "structure_build" and job["request"]["scene_id"] == sid


def test_only_people_who_edit_the_script_refresh_it(world: World):
    sid = _with_packet(world)
    r = world.client.post(_url(world, sid, "breakdown/refresh"), headers=world.headers(world.crew))
    assert r.status_code == 403
