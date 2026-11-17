# Panel edit lab (2026-11-17)

Question: when Zora or Sable adds, changes or deletes ONE shot, can the scene board paint only that panel and keep
every other approved panel as it is? (Today an add or a delete needs a whole repaint, which repaints every panel and
clears every approval.) Delete and reorder need no painting, so this lab covers add and change.

Start: the approved 6-panel portrait board of the tea-stall scene (`lab/portrait_board` run_001), copied to
`input/scene1/` with its writer text and the two place plates. Two edits in `input/scene1/edits.json` (lab fixtures,
never written anywhere): ADD a shot between 3 and 4 (over the customer's shoulder, Kasun pouring); CHANGE shot 5 from a
medium close-up profile to a wide from across the road.

| Call | What it tests |
|---|---|
| `writer_add`, `writer_change` | `board_writer`'s product prompt + `prompt/one_panel.md`: one panel, the board's world, geography and panels FIXED, the neighbours attached |
| `add_solo`, `change_solo` | ONE 9:16 picture, the panels before and after attached as references |
| `add_strip` | code assembles a sheet in the board's grid (panels 2, 3, an empty grey cell, 4, 5, 6); masked edit of the empty cell |
| `change_mask` | the product's method today: masked edit of the board over cell 5; `drift.json` in `summary.json` says whether the rest stayed (plan/2026-11-14 phase 0 (a)) |

```
.venv/Scripts/python.exe lab/panel_edit/run.py dry          # prompts, the sheet sent, the masks; no call
.venv/Scripts/python.exe lab/panel_edit/run.py paid --yes   # 2 writer + 4 LOW image calls (the person's yes)
.venv/Scripts/python.exe lab/panel_edit/run.py paid --yes --writer-from run_001 --only add_solo   # image only
```

Budget `LAB_BUDGET_USD` = $1.00, checked against each call's worst case (prices over-stated on purpose); a full run is
expected to cost about $0.35. Every paid call is in `runs/ledger.csv`. Read each run's `*_sheet.png` (the new panel
tagged in red among the old ones) and fill in its `judge.md`.

Found while building (free): the board writer puts the SHEET's layout into `world` ("six equal portrait panels ...
gutters"), which contradicts a one-panel picture; the solo prompt drops those sentences (`solo_world`). The product
should either keep layout out of `world` or filter it the same way.

## Runs

- **run_001** (2026-11-17, $0.289 booked): 2 writer + 4 LOW image calls, all done, no refusal.
  - Writer: both panels kept the fixed world, the colours, the props (scuffed flask, cream cup) and the landmark side
    (tree and pole frame right); no conflicts. ~1,100-1,200 output tokens, ~$0.02 a panel.
  - `add_solo`: sits among its neighbours unnoticed (same mannequins, grade, flask, kettle, trays, tree and pole). The
    pour falls between shot 3 (empty cup) and shot 4 (full cup). The camera is beside the customer rather than behind
    their shoulder: the over-the-shoulder is softened.
  - `add_strip`: the over-the-shoulder is right, but the model **repainted cells it was not asked to** (drift 29
    outside the mask; cells 5 and 6 became a rainy street and a walking blue mannequin). Code pasting the originals
    back is what saves it.
  - `change_solo`, `change_mask`: both a good wide from across the road, maroon stall on the far curb, Kasun small at
    the hatch, tree and pole frame right. `change_mask` drift 6.1: every cell re-encoded, not exact.
  - **Read**: the mask is not honoured (plan/2026-11-14 phase 0 (a) fails). The product's `repaint()` re-cuts every
    cell from the model's picture, so today an unchanged panel can be silently repainted. Solo painting needs no mask,
    no grid and gives the full 9:16; it matched the board as well as the masked edits did.
- **run_002** (2026-11-17, $0.196 booked; ledger $0.485 of $1.00): solo only, `--writer-from run_001`, the solo prompt
  gained `CAMERA_RULE` (the camera stands where the panel says; behind a shoulder = that back large in the near
  foreground). New fixture `change_first` (shot 1 becomes a side-on wide of the stall; one neighbour, panel 2).
  - `add_solo`: the camera fix worked: the customer is now large in the right foreground, three-quarter from behind,
    Kasun pouring beyond; same mannequins, flask, kettle, trays, tree and pole.
  - `change_solo_b`: the same edit as run_001's `change_solo` (only `CAMERA_RULE` added) came back with the same
    composition: maroon stall on the far curb, Kasun small at the hatch, a soft tuk-tuk crossing the foreground, tree
    and pole frame right. Repeatable.
  - `first_solo` (one neighbour): fits: the maroon three-wheeler side-on with the hatch, flask, kettle and trays, the
    bus-stop shelter, tree and pole frame right, a grey pedestrian mannequin as the world allows. One flaw: faint
    lettering-like marks on a shop facade top left (NO_TEXT not fully kept; the board is LOW and small).
  - Writer (`change_first`): kept the world, named the landmark "seen in the following counter panel", no conflicts.
  - **Read**: painting one panel alone with its neighbours as references works for add, change, and a scene's first
    shot, and repeats. Carry `CAMERA_RULE` into the product's one-panel prompt.
