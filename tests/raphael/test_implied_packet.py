"""plan/2026-11-12: Raphael reads a thing the script implies (house rule H-12) as a given thing of the scene: the
packet's implied phone reaches its opening, and each line heard through it carries it as its device (name only)."""

from __future__ import annotations

import pytest

from contracts.breakdown import packet
from contracts.raphael.packet import opening, scene_from_packet
from hiru_ai.core import house_rules
from hiru_ai.core.middleware import house_rules as hr_mw
from tests.breakdown.test_implied import PHONE, _made, _phones
from tests.hiru_ai.test_house_rules import _through


def test_the_packet_and_raphael_read_the_phone_as_a_given_thing():
    bd = _made({"E01-S02": [PHONE]})
    (phone,) = _phones(bd)
    p = packet.assemble(bd, "E01-S02")
    assert packet.incomplete(bd, p) == []  # an implied thing never makes the scene wait
    row = next(t for t in p["D_things"] if t["id"] == phone.id)
    assert row["source"] == "inferred" and row["holder_start"]
    text, _, _ = opening(p)
    assert f"{phone.id} phone [used]" in text and "(inferred)" in text
    assert f"[voice_message, phone {phone.id}]" in text
    devices = {b.line_id: b.device for b in scene_from_packet(p)[0].blocks if b.line_id}
    assert list(devices.values()) == ["phone", "phone"]  # the scene's two lines both come out of it, by name only


@pytest.mark.parametrize("name", ["raphael_planner", "raphael_cinematic"])
def test_both_raphael_stages_get_h12_at_the_end_of_their_system_prompt(name: str):
    system, ctx, _ = _through(name)
    assert system.endswith(house_rules.block(house_rules.select(("objects",))))
    assert hr_mw.used(ctx) == ["H-12 v2"]


def test_raphael_breakdown_is_not_subscribed_and_unchanged():
    system, ctx, _ = _through("raphael_breakdown")
    assert "HOUSE RULES" not in system and hr_mw.used(ctx) == []
