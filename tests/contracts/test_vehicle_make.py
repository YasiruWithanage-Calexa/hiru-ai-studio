"""plan/2026-11-24b D2: `scripts/vehicle_make.py` proposes the make from the look's leading make words (Love Hour's
L04 "Family car"), and nothing for a look that opens as a description (L03 "Food three-wheeler")."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import vehicle_make

L04 = ("BMW 520d. 2019 version,  A well-kept pearl-silver midsize four-door sedan with a roomy beige fabric rear "
       "bench, charcoal dashboard, right-hand-drive steering wheel.")
L03 = "A compact older maroon three-wheeler with a black vinyl roof and a side hatch food counter."


def test_the_make_comes_out_of_the_look():
    assert vehicle_make.propose(L04) == ("BMW 520d, 2019", "A well-kept pearl-silver midsize four-door sedan with a "
                                         "roomy beige fabric rear bench, charcoal dashboard, right-hand-drive steering "
                                         "wheel.")


def test_a_look_that_opens_as_a_description_has_no_proposal():
    assert vehicle_make.propose(L03) is None
    assert vehicle_make.propose("Interior of a compact right-hand-drive cash-transfer van. Two seats.") is None
    assert vehicle_make.propose("") is None
