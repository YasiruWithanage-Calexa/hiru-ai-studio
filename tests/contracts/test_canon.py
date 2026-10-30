from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.canon import (
    CanonCard,
    CanonKind,
    EpisodeRange,
    LookFields,
    format_code,
    look_sheet_prompt,
    look_stamp,
    look_wardrobe,
    looks_in_force,
    name_key,
    next_code,
    reference_sheet_aspect,
    reference_sheet_prompt,
    resolve_look,
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
    b = reference_sheet_prompt(CanonKind.CHARACTER, "Nimal", CanonCard(wardrobe="grey shirt", gender="male", age="40"))
    prefix = a.split("\nName:")[0]
    assert b.startswith(prefix)
    assert "Age:" not in a  # empty facts are left out, not printed blank
    loc = reference_sheet_prompt(CanonKind.LOCATION, "Harbour", CanonCard(look="lighthouse"), aspect_ratio="9:16")
    assert "no people" in loc and "9:16" in loc


def test_name_key():
    assert name_key("MRS. PERERA") == name_key("Mrs Perera") == "mrs perera"
    assert name_key("NIMAL (V.O.)") == "nimal"
    assert name_key("කමලා") == "කමලා"
    assert name_key("ශ්‍රී") == "ශ්‍රී"  # ZWJ conjunct kept


def test_a_character_sheet_is_five_wide_panels_in_a_plain_outfit():
    card = CanonCard(age="late 20s", gender="Female", appearance="long wavy dark brown hair",
                     wardrobe="faded blue saree")
    text = reference_sheet_prompt(CanonKind.CHARACTER, "Nethmi", card, aspect_ratio="9:16")
    assert "five panels" in text and "cropped at the neck" in text and "Right panel: a close-up portrait" in text
    assert "Subject: one adult woman" in text and "sports bra and fitted gym shorts" in text
    assert "long wavy dark brown hair" in text
    assert "saree" not in text, "the story wardrobe is a look, not part of the base sheet"
    assert "Aspect ratio 16:9" in text and "9:16" not in text, "a vertical production still gets a wide sheet"
    assert reference_sheet_aspect(CanonKind.CHARACTER, "9:16") == "16:9"
    assert reference_sheet_aspect(CanonKind.LOCATION, "9:16") == "9:16"


def test_a_man_gets_trunks_and_the_female_word_does_not_match_male():
    man = reference_sheet_prompt(CanonKind.CHARACTER, "Kasun", CanonCard(age="30", gender="Male"))
    assert "Subject: one adult man" in man and "gym shorts" in man and "sports bra" not in man
    woman = reference_sheet_prompt(CanonKind.CHARACTER, "Kamala", CanonCard(age="52", gender="female"))
    assert "Subject: one adult woman" in woman


def test_only_a_confirmed_adult_is_shown_bare_armed_in_gym_wear():
    for card in (CanonCard(age="10", gender="girl"), CanonCard(age="17", gender="male"),
                 CanonCard(gender="female"), CanonCard(age="teen", gender="female"),
                 CanonCard(age="30")):
        text = reference_sheet_prompt(CanonKind.CHARACTER, "X", card)
        assert "gym" not in text and "sports bra" not in text and "Subject: one person" in text
        assert "grey t-shirt and fitted grey trousers" in text


def test_episode_ranges_are_read_and_written_as_from_and_to():
    r = EpisodeRange.model_validate({"from": 36, "to": 60})
    assert (r.first, r.last) == (36, 60) and r.model_dump(by_alias=True) == {"from": 36, "to": 60}
    assert EpisodeRange.model_validate({"from": 44, "to": 44}).last == 44
    for bad in ({"from": 5, "to": 4}, {"from": 0, "to": 3}, {"from": 1}):
        with pytest.raises(ValidationError):
            EpisodeRange.model_validate(bad)


def test_a_look_needs_a_name_and_at_least_one_range():
    ok = LookFields.model_validate({"name": "Office worker", "ranges": [{"from": 21, "to": 35}]})
    assert ok.outfit == "" and ok.accessories == ""
    with pytest.raises(ValidationError):
        LookFields.model_validate({"name": "Office worker", "ranges": []})
    with pytest.raises(ValidationError):
        LookFields.model_validate({"name": "", "ranges": [{"from": 1, "to": 2}]})


def test_a_look_sheet_keeps_the_person_and_changes_the_clothes():
    look = LookFields.model_validate({
        "name": "Heiress reveal", "ranges": [{"from": 36, "to": 60}],
        "outfit": "maroon silk saree with a gold border", "hair": "smooth bun with jasmine",
        "accessories": "gold jhumka earrings, a steel watch, a navy cap"})
    text = look_sheet_prompt("Nethmi", look)
    assert "five panels" in text and "Right panel: a close-up portrait" in text, "the base sheet's layout"
    assert "Image 1 is the base character sheet" in text and "replace them completely" in text
    assert "Outfit: maroon silk saree with a gold border" in text
    assert "Accessories: gold jhumka earrings, a steel watch, a navy cap" in text
    assert "Makeup:" not in text, "empty facts are left out, not printed blank"
    assert "Aspect ratio 16:9" in text and "gym" not in text and "swim" not in text
    other = look_sheet_prompt("Kasun", LookFields.model_validate({"name": "Office", "ranges": [{"from": 1, "to": 2}]}))
    assert other.startswith(text.split("\nCharacter:")[0]), "static wording first, then this look's facts"


def _look(lid: str, ranges: list[tuple[int, int]], status: str = "ready", entity: str = "kamala") -> dict:
    return {"id": lid, "entity_id": entity, "status": status, "ranges": [{"from": a, "to": b} for a, b in ranges],
            "outfit": f"{lid} outfit", "hair": "", "makeup": "", "accessories": "", "sheet_assets": [{"path": lid}]}


def test_the_look_in_force_is_the_narrowest_ready_one_and_a_scene_pick_wins():
    heiress, hospital = _look("heiress", [(36, 60)]), _look("hospital", [(44, 44)])
    draft = _look("draft", [(44, 44)], status="draft")
    looks = [heiress, hospital, draft]
    assert resolve_look(looks, 44) is hospital and resolve_look(looks, 40) is heiress
    assert resolve_look(looks, 10) is None
    twin = _look("twin", [(30, 54)])  # 25 wide, like Heiress
    assert resolve_look([heiress, twin], 40) is None, "two ready looks of one width are ambiguous"
    assert looks_in_force(looks, [], 44) == {"kamala": hospital}
    assert looks_in_force(looks, [{"entity_id": "kamala", "look_id": "heiress"}], 44) == {"kamala": heiress}
    assert looks_in_force(looks, [{"entity_id": "kamala", "look_id": "draft"}], 44) == {"kamala": hospital}
    assert looks_in_force(looks, [], None) == {}


def test_a_looks_stamp_follows_its_wardrobe_and_sheet_not_its_name():
    look = _look("heiress", [(36, 60)])
    assert look_stamp({**look, "name": "Renamed", "ranges": [{"from": 1, "to": 2}]}) == look_stamp(look)
    assert look_stamp({**look, "hair": "loose"}) != look_stamp(look)
    assert look_stamp({**look, "sheet_assets": [{"path": "new.png"}]}) != look_stamp(look)
    assert look_wardrobe({**look, "hair": "a bun."}) == "outfit heiress outfit; hair a bun"
