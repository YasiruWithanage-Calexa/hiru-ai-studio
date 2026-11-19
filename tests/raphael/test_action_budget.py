"""The action budget (plan/2026-11-18c, lab/action_budget): the person's known cases, in the planners' own words.

Counted in actions, never seconds. Bad: Love Hour 4 2B-1 (the car exit, wrong door in every take), the phone-drop
master of Api Denna E01-S03. Risky: the umbrella opening mid-walk. Good: the coverage insert and walk-on.
"""

from __future__ import annotations

from contracts import action_budget as ab
from contracts.raphael import checks
from tests.raphael.test_ledger import bin_of, clip

CAR_EXIT = [  # Love Hour 4, "Anudi arrives", 2B-1 (what_we_see)
    "The car rolls its final short distance toward the curb; Anudi is still seated.",
    "The driver stops; Anudi loops the handbag over her left forearm and takes the closed umbrella in her left hand "
    "while retaining the phone in her right.",
    "The rear curb-side door swings open; with the door panel masking the grip, Anudi steps out and pushes it closed "
    "with her left forearm, phone still in right hand, handbag on left forearm and closed umbrella in left hand.",
    "Anudi gives the seated driver a small closed-lip nod and begins walking screen right toward the office.",
    "Anudi continues the same walking pace, carrying all three belongings; the driver stays seated.",
]
UMBRELLA_MID_WALK = [  # Love Hour 4, 2C-1
    "Anudi walks screen right with the umbrella still closed, phone in right hand and handbag on left forearm.",
    "Sparse rain begins falling; Anudi shortens her next step and raises the closed umbrella in her left hand.",
    "With the mechanism obscured by her torso, the umbrella canopy opens above her head; the phone stays in her right "
    "hand and the handbag stays on her left forearm.",
    "Anudi continues walking screen right beneath the fully open umbrella.",
]
PHONE_MASTER = [  # Api Denna E01-S03, 3A-1, the saved plan
    "Anudi maintains her rightward stride, umbrella upright and phone in right hand.",
    "Anudi walks past the vehicle and moves the phone toward the outer pocket at her right hip.",
    "The phone misses the outer pocket, slips from her right hand and lands on the roadside; Anudi continues right "
    "without looking back.",
    "The phone rests on the road as Anudi maintains the same rightward stride.",
]
COVERAGE_INSERT = [  # E01-S03 coverage, 3A-1
    "Her right hand rests with the phone beside the pocket while the bag hangs at her left hip.",
    "Her right hand guides the phone partly against the outer pocket as the handbag swings with her rightward step.",
    "The phone's lower edge catches the rim; the bag swings right, the phone tips outward from her fingers and lands "
    "on the roadside.",
    "The bag clears the right edge and the phone lies flat on the wet roadside.",
    "Rain dots the road around the phone.",
]
COVERAGE_WALK_ON = [  # E01-S03 coverage, 3B-1
    "She continues her established rightward stride, eyes along the road ahead.",
    "She walks right and clears the right edge at 3.5 seconds; the phone remains on the road.",
    "Rain dots the roadside around the phone.",
]


def test_the_known_bad_clips_are_over_and_the_good_ones_fit():
    exit_ = ab.count(CAR_EXIT)
    assert len(exit_.hard) >= 4 and exit_.travel and len(exit_.over()) == 3
    assert ab.count(UMBRELLA_MID_WALK).over() == [ab.count(UMBRELLA_MID_WALK).over()[0]]  # only: hard while walking
    assert "while a person travels" in ab.count(UMBRELLA_MID_WALK).over()[0]
    assert ab.count(PHONE_MASTER).over()
    assert ab.count(COVERAGE_INSERT).over() == [] and len(ab.count(COVERAGE_INSERT).hard) == 1
    assert ab.count(COVERAGE_WALK_ON).over() == []


def test_one_event_told_in_several_verbs_is_one_action():
    drop = ab.count(["The phone catches the rim, tips outward, falls and lands on the road."])
    assert [a.label for a in drop.hard] == ["falls"]
    umbrella = ab.count(["She opens the umbrella.", "The umbrella opens above her head."])
    assert len(umbrella.hard) == 1


def test_nouns_body_parts_and_weather_are_not_actions():
    for text in ("The outer pocket of the open box sits in place.", "He lifts his eyes and takes a breath.",
                 "Aruni takes several measured steps.", "The handshake takes place outside the frame.",
                 "Rain begins to fall around her.", "A bead slips off the rim of the umbrella.",
                 "Both hold their places beside the counter."):
        assert ab.count([text]).hard == [], text


def test_a_hand_routine_is_several_hard_actions():
    tea = ab.count(["Kasun lifts the flask, pours into the cup, sets the flask down and takes the cup."])
    assert len(tea.hard) >= 3 and tea.over()


def test_a_state_is_not_an_action_and_a_repeated_beat_counts_once():
    assert ab.count(["Kasun keeps the flask in his left hand.", "The phone remains on the road."]).actions == ()
    same = "She closes the rear door and gives a small nod."
    assert len(ab.count([same, same]).actions) == 2


def test_a_door_opened_and_never_closed_is_left_open():
    first = ["A wide: the car stops.", "Beside the already open rear door, Anudi gets out.",
             "Anudi nods to the driver and walks toward the office."]
    assert ab.door_left_open(first) == 1
    fixed = [*first[:2], "Anudi closes the rear door while retaining her belongings.", first[2]]
    assert ab.door_left_open(fixed) is None
    assert ab.door_left_open(["She walks past the closed shop."]) is None


def test_a_speaker_turned_away_in_the_opening():
    assert ab.turned_away("Standing screen left behind the counter, initially facing into the vehicle") != ""
    assert ab.turned_away("Kasun stands with his back to the camera") != ""
    assert ab.turned_away("Three-quarter toward the road, eyes past the lens") == ""


def test_raphael_gets_blocking_faults_it_must_fix():
    over = clip("c01", [0], beats=CAR_EXIT, slate="2B-1")
    found = checks.action_budget(bin_of(over))
    assert [f.key for f in found] == ["action_budget:c01"] and checks.blocking(found) == found
    assert "H-16" in found[0].sentence and "door" in found[0].sentence
    good = clip("c02", [0], beats=COVERAGE_INSERT, slate="3A-1")
    assert checks.action_budget(bin_of(good)) == []


def test_raphael_is_told_about_an_open_door_and_a_hidden_speaker():
    out = clip("c01", [0], beats=["Beside the already open rear door, Anudi gets out."], slate="2C-1")
    walk = clip("c02", [1], beats=["Anudi walks toward the office."], slate="2D-1")
    assert [f.key for f in checks.action_budget(bin_of(out, walk))] == ["door_open:c01"]
    speaker = clip("c03", [0], {"id": "C01", "action": "speaks L6",
                                "position": "Behind the counter, initially facing into the vehicle"},
                   beats=["Kasun turns toward the road.", "Kasun's lips move to L6."], slate="1D-1",
                   lines=["L6"], speaks=True)
    assert [f.key for f in checks.action_budget(bin_of(speaker))] == ["speaker_hidden:c03"]

