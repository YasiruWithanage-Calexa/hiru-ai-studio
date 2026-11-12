"""plan/2026-11-12 §3.2-3.3: the reader records what the script implies (house rule H-12), code makes it a thing of the
scene and a canon card marked inferred, and two report-only checks say when a heard line has no device.

The model is scripted: the lab's gold Ekama answers, with Scene 2's answer given an `implied` phone the way a reader
following H-12 writes it ("Aruni's voice message plays." / "Mudalali calls." never name the phone)."""

from __future__ import annotations

import copy
from typing import Any

from contracts.breakdown import build as build_mod
from contracts.breakdown import checks, fill, packet
from contracts.breakdown import run as brun
from contracts.breakdown.schema import EpisodeW
from hiru_ai.systems.breakdown.breakdown_build.graph import canon_rows
from tests.breakdown.test_breakdown_run import Scripted, _upload

PHONE = {
    "name": "Phone",
    "holder": "C01",
    "where": "in a dashboard mount beside the wheel",
    "blocks": [3, 4, 5, 6],
    "why": "Aruni's voice message plays and Mudalali calls: both voices come out of it",
}


class Implying(Scripted):
    """The gold answers, with `implied` added to the scenes named."""

    def __init__(self, implied: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__()
        for sid, items in implied.items():
            self.eps[sid] = {**copy.deepcopy(self.eps[sid]), "implied": items}


def _made(implied: dict[str, list[dict[str, Any]]]) -> Any:
    res = brun.create([_upload()], Implying(implied).calls(), production="ekama", workers=1)
    assert res.memory is not None
    return res.memory


def _phones(bd: Any) -> list[Any]:
    return [e for e in bd.entities if e.kind == "thing" and e.name == "phone"]


def test_an_implied_phone_becomes_a_thing_of_the_scene_with_its_holder_and_place():
    bd = _made({"E01-S02": [PHONE]})
    (phone,) = _phones(bd)
    assert phone.card["summary"].source == "inferred" and "voice message" in phone.card["summary"].value
    assert phone.card["details"].value == "in a dashboard mount beside the wheel"
    sc = bd.scene("E01-S02")
    use = next(t for t in sc.brief["things"] if t["thing"] == phone.id)
    assert use == {"thing": phone.id, "role": "used", "holder_start": "C01", "holder_end": "C01", "source": "inferred"}
    for n in (3, 4, 5, 6):
        b = sc.blocks[n - 1]
        assert b["device"] == f"phone {phone.id}"
        assert all(phone.id in e["things"] for e in b["events"])
    assert sc.blocks[0]["device"] == "" and sc.blocks[6]["device"] == ""


def test_a_thing_of_the_same_name_is_reused_never_doubled():
    bd = _made({"E01-S02": [PHONE], "E01-S03": [{**PHONE, "blocks": [1]}]})
    assert len(_phones(bd)) == 1
    before = len(bd.entities)
    again = EpisodeW.model_validate({"scenes": [_brief(bd, "E01-S02")]}).scenes[0]
    build_mod.apply_implied(bd, bd.scene("E01-S02"), again)
    assert len(bd.entities) == before  # a refresh that implies it again finds the one there is


def _brief(bd: Any, sid: str) -> dict[str, Any]:
    sc = bd.scene(sid)
    return {"scene": sid, **sc.brief, "blocks": [{"kind": "action", "spans": []} for _ in sc.blocks]}


def test_a_holder_not_in_the_scene_is_dropped_and_a_bad_block_number_is_ignored():
    bd = _made({"E01-S02": [{**PHONE, "holder": "C05", "blocks": [4, 99]}]})
    sc = bd.scene("E01-S02")
    (phone,) = _phones(bd)
    use = next(t for t in sc.brief["things"] if t["thing"] == phone.id)
    assert use["holder_start"] == "" and sc.blocks[3]["device"] == f"phone {phone.id}"


def test_a_name_that_is_not_a_plain_noun_is_not_recorded_and_is_reported():
    bd = _made({"E01-S02": [{**PHONE, "name": "the phone Aruni secretly bugged"}]})
    assert not [e for e in bd.entities if "bugged" in e.name]
    found = checks.implied(bd)
    assert len(found) == 1 and not found[0].blocking and found[0].scene == "E01-S02"


def test_a_heard_line_with_no_device_is_reported_never_blocking():
    bare = _made({})
    found = [f for f in checks.devices(bare) if f.scene == "E01-S02"]
    assert {f.message.split()[0] for f in found} == {"E01-S02-B04", "E01-S02-B06"}
    assert not any(f.blocking for f in found)
    p = packet.assemble(bare, "E01-S02")
    assert packet.incomplete(bare, p) == []  # reported in the packet's open notes, never a wait
    assert any("names no device" in x for x in p["I_open"])
    with_phone = _made({"E01-S02": [PHONE]})
    assert not [f for f in checks.devices(with_phone) if f.scene == "E01-S02"]


def test_the_canon_card_is_inferred_and_a_person_s_entry_is_never_touched():
    bd = _made({"E01-S02": [PHONE]})
    cards = fill.canon_cards(bd)
    phone = next(c for c in cards if c["name"].lower() == "phone")
    assert phone["inferred"] is True and phone["kind"] == "prop"
    assert not any(c["inferred"] for c in cards if c is not phone)
    made = canon_rows(cards, [], production_id="p", actor=None, aspect_ratio="16:9")
    version = next(v for e, v in made if e["name"].lower() == "phone")
    assert version["source"] == "inferred"
    assert {v["source"] for e, v in made if e["name"].lower() != "phone"} == {"extract"}
    mine = [{"kind": "prop", "name": "Phone", "aliases": [], "code": "P01"}]
    assert not [e for e, _ in canon_rows([phone], mine, production_id="p", actor=None, aspect_ratio="16:9")]
