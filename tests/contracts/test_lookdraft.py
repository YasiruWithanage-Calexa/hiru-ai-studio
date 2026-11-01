"""Draft looks from a card: rules, and the check on what a model proposes."""
from __future__ import annotations

from contracts.lookdraft import by_rules, clean_proposals, look_row

KASUN = ("Simple plain T-shirts or casual shirts; Dark jeans; Simple sandals or sneakers; "
         "Later, as his business grows, clean smart-casual clothing")
ANUDI = "Modern casual dresses; Elegant blouse and trousers; Simple jewelry; Stylish handbag"


def spans(looks):
    return [(lk.name, [(r.first, r.last) for r in lk.ranges]) for lk in looks]


def test_a_wardrobe_that_changes_later_becomes_two_looks_covering_every_episode():
    looks = by_rules({"wardrobe": KASUN}, 3)
    assert spans(looks) == [("Everyday", [(1, 2)]), ("Later", [(3, 3)])]
    assert "Dark jeans" in looks[0].outfit and "smart-casual" in looks[1].outfit
    assert "Later" not in looks[1].outfit  # the marker is the look's name, not its wording


def test_one_episode_or_no_change_is_one_look():
    assert spans(by_rules({"wardrobe": KASUN}, 1)) == [("Everyday", [(1, 1)])]
    assert spans(by_rules({"wardrobe": ANUDI}, 5)) == [("Everyday", [(1, 5)])]


def test_accessories_leave_the_outfit_but_garments_stay():
    [look] = by_rules({"wardrobe": ANUDI}, 3)
    assert look.accessories == "Simple jewelry; Stylish handbag"
    assert look.outfit == "Modern casual dresses; Elegant blouse and trousers"


def test_hair_and_makeup_come_from_short_notes_in_the_appearance():
    card = {"wardrobe": ANUDI, "appearance": "Long dark black hair; Elegant natural makeup; Medium skin"}
    [look] = by_rules(card, 3)
    assert (look.hair, look.makeup) == ("Long dark black hair", "Elegant natural makeup")
    run_on = {"wardrobe": ANUDI, "appearance": "Sri Lankan woman " + "with long dark hair " * 8}
    assert by_rules(run_on, 3)[0].hair == ""  # a whole description is not a hair note


def test_no_wardrobe_means_no_look():
    assert by_rules({"summary": "Speaks in the scripts as Nimal."}, 3) == []
    assert by_rules({}, 3) == []


def test_a_later_in_the_middle_of_a_sentence_is_not_a_change():
    assert spans(by_rules({"wardrobe": "A cream sari she irons later in the day"}, 4)) == [("Everyday", [(1, 4)])]


def raw(**over):
    return {"name": "Office", "from": 1, "to": 2, "outfit": "grey suit", "hair": "", "makeup": "", "accessories": "",
            **over}


def test_model_looks_are_kept_when_they_hold_up_and_clipped_to_the_drama():
    kept = clean_proposals([raw(), raw(name="Wedding", **{"from": 3, "to": 99}, outfit="red saree")], 3)
    assert spans(kept) == [("Office", [(1, 2)]), ("Wedding", [(3, 3)])]


def test_model_looks_that_do_not_hold_up_are_dropped():
    bad = [raw(name=""), raw(outfit=""), raw(**{"from": 5, "to": 6}), raw(**{"from": 3, "to": 1}),
           raw(name="Office"), raw(name="office", outfit="again")]
    assert spans(clean_proposals(bad, 3)) == [("Office", [(1, 2)])]  # the repeated name is dropped
    assert len(clean_proposals([raw(name=f"L{i}") for i in range(9)], 3)) == 4


def test_a_look_row_is_a_draft_with_the_table_columns():
    [look] = by_rules({"wardrobe": ANUDI}, 3)
    row = look_row("e1", "p1", look, "u1")
    assert row == {"entity_id": "e1", "production_id": "p1", "name": "Everyday", "ranges": [{"from": 1, "to": 3}],
                   "outfit": look.outfit, "hair": "", "makeup": "", "accessories": look.accessories,
                   "created_by": "u1"}
    assert "status" not in row  # the column defaults to draft
