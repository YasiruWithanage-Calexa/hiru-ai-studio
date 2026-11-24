# Place views lab: findings (2026-11-24)

Question: can ONE sheet of a place's main possible views be written and painted at CANON time (before any shot),
with three answers about the place picking one of four FIXED six-view templates and the AI writing each view?
Love Hour places, read-only (`fetch.py`). Budget $0.60, raised to $0.80 for r2's worst-case check; spent $0.466.

## Revision 1 (`runs/r1`, $0.308)

| place | template picked | plate | result |
|---|---|---|---|
| Colombo roadside | outside (long) | yes | one place in every view; BUT "Looking left" and "Looking right" faced the same frontage; the vending bay (where the food three-wheeler parks) painted as a full lit stall |
| KASUN'S Restaurant | both (room) | no, words only | best: maroon front, cane lamps, steel counter, lattice the same in all six; Detail 2 a plain table |
| Kasun's small food preparation workspace | inside (room) | no, words only | the four walls fit: desk left, steel shelves and stove right, window far, door opposite |
| Family car (BMW 520d) | vehicle (small) | yes | front 3/4, side, rear 3/4, inside forward to the right-hand wheel, inside back to the beige bench, dashboard; one car |

All four templates picked right; all four sheets cut clean.

## Revision 2 (`runs/r2`, roadside + restaurant, $0.158)

Fixes: the outside template's first four views share ONE anchor spot and turn 0 / 90 left / 90 right / 180, each
saying where the main frontage is; a new `empty` list: spaces where something that comes and goes stands (a parked
vehicle, a cart) are kept bare and anything the plate shows there is left out; details only from what scenes use or the
card names.

| place | result |
|---|---|
| roadside | FIXED turns: Looking left has the frontage at the right edge, Looking right at the left edge, Reverse looks across the road with the frontage out of frame. The writer listed the three-wheeler bay as empty and nothing is parked; but the bay is not clearly drawn as a space of its own, and the shop's goods table still stands on the pavement (the shop itself is fixed, rightly kept) |
| restaurant | still one place, sign left blank by the painter (the WRITER invented sign text "KASUN'S — SRI LANKAN FOOD & COFFEE" against its rule; the painter's no-text rule won). Detail 1 the counter (good); Detail 2 still a table under a pendant (the rule did not hold) |

## Verdict

The idea holds: fixed templates by three answers, the AI writing the views, give a cuttable sheet of one connected
place for outside, inside-and-outside, inside-only and vehicle places, with or without a plate. Open:
- the empty space is honoured (nothing parked) but not shown as a clear bare space; worth one more line in the layout
  ("a bare concrete bay, X metres, between A and B") if frames need to find it;
- the writer still breaks two soft rules (sign text, a plain-table detail): code should check them (no quoted text in
  views unless on the card; a detail must name a thing from the card or a scene) rather than trust the prompt.
