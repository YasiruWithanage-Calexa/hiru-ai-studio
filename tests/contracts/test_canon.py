from __future__ import annotations

from contracts.canon import (
    CanonCard,
    CanonKind,
    format_code,
    name_key,
    next_code,
    reference_sheet_prompt,
    voice_pin,
)


def test_codes():
    assert format_code(CanonKind.CHARACTER, 1) == "C01"
    assert format_code(CanonKind.PROP, 120) == "P120"
    assert next_code(CanonKind.LOCATION, {"L01", "L02", "L04"}) == "L03"


def test_voice_pin_is_derived_and_never_guessed():
    card = CanonCard(voice="low, clipped", gender="Female", age="52", accent="a Sri Lankan (southern) accent")
    assert voice_pin(card) == "low, clipped female voice (52), a Sri Lankan (southern) accent"
    assert voice_pin(CanonCard(age="30")) == "voice (30), a Sri Lankan (Colombo) accent"
    assert voice_pin(CanonCard(summary="the mother")) == ""


def test_reference_prompt_static_part_first():
    a = reference_sheet_prompt(CanonKind.CHARACTER, "Kamala", CanonCard(wardrobe="blue saree"))
    b = reference_sheet_prompt(CanonKind.CHARACTER, "Nimal", CanonCard(wardrobe="grey shirt"))
    prefix = a.split("\nName:")[0]
    assert b.startswith(prefix) and "Wardrobe: blue saree" in a
    assert "Age:" not in a  # empty facts are left out, not printed blank
    loc = reference_sheet_prompt(CanonKind.LOCATION, "Harbour", CanonCard(look="lighthouse"), aspect_ratio="9:16")
    assert "no people" in loc and "9:16" in loc


def test_name_key():
    assert name_key("MRS. PERERA") == name_key("Mrs Perera") == "mrs perera"
    assert name_key("NIMAL (V.O.)") == "nimal"
    assert name_key("කමලා") == "කමලා"
    assert name_key("ශ්‍රී") == "ශ්‍රී"  # ZWJ conjunct kept
