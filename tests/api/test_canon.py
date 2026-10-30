from __future__ import annotations

from uuid import uuid4

import pytest

from tests.api.conftest import World


def add_entity(world: World, code: str = "C01", name: str = "Kamala", kind: str = "character",
               production=None) -> str:
    canon = world.repos.canon  # type: ignore[attr-defined]
    row = canon.add(production_id=str(production or world.production), kind=kind, code=code, name=name,
                    aliases=["කමලා"], core=True, locked=False, current_version_id=None)
    vid = str(uuid4())
    canon.version_rows[vid] = {"id": vid, "entity_id": row["id"], "version": 1, "card": {"voice": "low"},
                               "wardrobe_anchor": "", "voice_pin": "low voice", "reference_prompt": "",
                               "source": "extract", "created_by": None, "created_at": "2026-10-23T00:00:00+00:00"}
    row["current_version_id"] = vid
    return str(row["id"])


def url(world: World, entity_id: str = "", suffix: str = "") -> str:
    base = f"/v1/productions/{world.production}/canon"
    return f"{base}/{entity_id}{suffix}" if entity_id else base


def test_everyone_on_the_production_reads_the_canon(world: World):
    eid = add_entity(world)
    add_entity(world, "L01", "Harbour", "location")
    rows = world.client.get(url(world), headers=world.headers(world.reviewer)).json()
    assert [r["code"] for r in rows] == ["C01", "L01"]
    assert rows[0]["current"]["voice_pin"] == "low voice" and rows[0]["current_version"] == 1
    only = world.client.get(url(world) + "?kind=location", headers=world.headers(world.crew)).json()
    assert [r["code"] for r in only] == ["L01"]
    detail = world.client.get(url(world, eid), headers=world.headers(world.writer)).json()
    assert [v["version"] for v in detail["versions"]] == [1]
    assert world.client.get(url(world), headers=world.headers(world.outsider)).status_code == 404


def test_a_new_version_derives_the_pins_from_the_card(world: World):
    eid = add_entity(world)
    card = {"summary": "the mother", "age": "52", "gender": "female", "voice": "low, clipped",
            "wardrobe": "faded blue saree"}
    r = world.client.post(url(world, eid, "/versions"), json={"card": card}, headers=world.headers(world.director))
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["version"] == 2 and v["source"] == "user"
    assert v["voice_pin"] == "low, clipped female voice (52), a Sri Lankan (Colombo) accent"
    assert v["wardrobe_anchor"] == "faded blue saree"
    assert "Outfit in every panel: a plain solid-color fitted sports bra and fitted gym shorts" in v["reference_prompt"]
    assert "saree" not in v["reference_prompt"] and "16:9" in v["reference_prompt"]
    detail = world.client.get(url(world, eid), headers=world.headers(world.director)).json()
    assert detail["current_version"] == 2


def test_explicit_pins_win(world: World):
    eid = add_entity(world)
    body = {"card": {"voice": "low"}, "voice_pin": "a hoarse whisper", "wardrobe_anchor": "white cardigan"}
    v = world.client.post(url(world, eid, "/versions"), json=body, headers=world.headers(world.producer)).json()
    assert (v["voice_pin"], v["wardrobe_anchor"]) == ("a hoarse whisper", "white cardigan")


def test_locked_items_must_be_unlocked_before_changing(world: World):
    eid = add_entity(world)
    h = world.headers(world.director)
    locked = world.client.post(url(world, eid, "/lock"), headers=h).json()
    assert locked["locked"] is True
    assert world.client.post(url(world, eid, "/versions"), json={"card": {}}, headers=h).status_code == 409
    assert world.client.patch(url(world, eid), json={"core": False}, headers=h).status_code == 409
    world.client.post(url(world, eid, "/unlock"), headers=h)
    assert world.client.patch(url(world, eid), json={"core": False}, headers=h).json()["core"] is False
    actions = [e["action"] for e in world.repos.audit.entries]  # type: ignore[attr-defined]
    assert actions.count("canon.lock") == 1 and "canon.unlock" in actions


def test_rename_clash_is_409(world: World):
    eid = add_entity(world)
    add_entity(world, "C02", "Nimal")
    r = world.client.patch(url(world, eid), json={"name": "NIMAL"}, headers=world.headers(world.director))
    assert r.status_code == 409 and "C02" in r.json()["detail"]


@pytest.mark.parametrize("role", ["writer", "crew", "reviewer"])
def test_only_canon_editors_change_it(world: World, role: str):
    eid = add_entity(world)
    h = world.headers(getattr(world, role))
    assert world.client.post(url(world, eid, "/versions"), json={"card": {}}, headers=h).status_code == 403
    assert world.client.post(url(world, eid, "/lock"), headers=h).status_code == 403


def test_an_entity_of_another_production_is_404(world: World):
    eid = add_entity(world, production=world.other_production)
    assert world.client.get(url(world, eid), headers=world.headers(world.admin)).status_code == 404
