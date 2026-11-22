# plan/2026-11-22: what is built

Phases 0 to 5 built offline on 2026-11-22 (backend only, uncommitted), no paid call. The lab: `lab/board_grid/`
(free sweep + run_001, $0.436 booked). Phase 6 (`scripts/recut_boards.py --apply` on the hosted project) is the
person's.

Decisions taken as the plan recommended (the person said "implement it"; each is the person's to overrule):
**D1** a bad cut fails the part, never repaints by itself; **D2** a re-cut approved part loses its approval; **D3**
first frames painted from a bad part are only listed.

| Phase | State |
|---|---|
| 0 inputs | built: `lab/board_grid/fetch.py` also reads `writer` and `colours` (GET only); `input/love_p2` re-fetched |
| 1 cutter | built: `pictures.py` (lab `grid.py` ported unchanged; old cut kept as `_even_boxes`), `tests/contracts/test_board_grid.py` |
| 2 engine | built: `board.py` `paint()` fails a part on `cut_problems`, `bad_cut()`; `tests/hiru_ai/test_board_grid_cut.py` |
| 3 writer | built: `board_layout_free` in `board_prompt`, `writer_message` without a grid, one rule in `board_writer/prompts/system.md`; tests in `test_board_grid.py`, the agent test, `tests/api/test_boards.py` |
| 4 re-cut | built: `scripts/recut_boards.py`, `tests/contracts/test_recut_boards.py`; dry run on the hosted project done (below) |
| 5 docs | built: `docs/scene_board/README.md` (§ How it works, 4), `CLAUDE.md` Scene board paragraph, this file |
| 6 apply | **the person's**: `python scripts/recut_boards.py --apply`, look at the mended parts, approve |

## Changes from the plan (all found while building)

- **Phase 0 fixtures.** The board pictures are ~2 MB each (63 MB for the stored boards), over the plan's 3 MB limit, so
  nothing is copied into `tests/fixtures/`: the parity tests read `lab/board_grid/` and skip when it is gone (as
  `tests/raphael/test_lab_parity.py` does). They take ~50 s (two cutters over 31 real boards).
- **Phase 3 golden.** The plan's golden ("`board_prompt` on the saved writer equals the lab's B prompt") cannot hold:
  Update board edited this part's writer after it was painted (shots 9 and 14 were repainted alone on 2026-11-22
  ~01:55 local), so the saved writer no longer gives the saved prompt. The golden is narrower and exact instead:
  `board_layout_free` on the saved prompt's World paragraph equals run_001 B's World line, byte for byte.
- **Phase 4: parts that hold both.** The plan (and the lab sweep) skipped any part with a panel painted alone. The
  case board 34683023 is now such a part: shots 9 and 14 painted alone, shots 10-13 still the bad grid crops. The
  script re-cuts the GRID cells only (a `box`, `source` not "panel"), each at its grid position (`panel`) in a grid of
  the size the part was painted with (read from its prompt, "N photorealistic film stills"); panels painted alone are
  left as they are and drawn on the redrawn sheet from their own pictures.
- **Synthetic test pictures.** Three of the first synthetic tests were wrong (a wide grid on a tall sheet; a gutter
  inside the old search window; a white card running into the crop's edge) and were fixed in the test, not in the
  ported code.

## Phase 4 dry run (hosted project, read only, 2026-11-22)

| Part | Scene | Approved | Saved cut | New cut | First frames from it |
|---|---|---|---|---|---|
| 34683023 part 2/2 (v7, current) | de75bc31 (Love Hour) | no | shots 10-13: two panels in one crop / empty cell | mends | none |
| 63817917 part 2/2 (v3) | de75bc31 | no | two panels in each crop | mends | none |
| 72c07de3 part 2/2 | 48fbb071 | **yes** | empty cell inside a crop | mends | **2 accepted finals** (7615495f, 49e2d345) |
| 72c5aadb part 2/2 (v5) | de75bc31 | no | two panels in one crop | **cannot mend**: the model painted 7 panels in uneven rows for a 3-panel ask; left as it is | none |

6 parts skipped (no grid cell left, or no panel count in the prompt).

## Known limits

- A panel whose bottom or top 15 % or more is pure white from edge to edge (a drawn white wall or card with no
  outline) reads as an empty cell beside paint and fails its part; the person paints again. Not seen in the 22 stored
  boards or run_001.
- Panels the wrong shape for the sheet (square cells on a wide board with 5-6 shots) are not touched (plan §7).
- Pillow's `getdata` warns of its removal in Pillow 14 (2027-10); the ported code keeps it, as the lab has it.

## Checks

`ruff check src tests scripts`, `mypy`, `pytest -q` — results in the chat that built this (2026-11-22).
