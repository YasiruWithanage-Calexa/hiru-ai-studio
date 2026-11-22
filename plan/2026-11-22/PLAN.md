# Scene board: cut the grid that was painted, and never save a bad cut (plan/2026-11-22)

Revision 1 (2026-11-22). Nothing in this plan is built. It changes how a painted Scene board is cut into one picture
per shot, so a board the image model painted in another grid than asked is still cut panel by panel, and a cut that
is still wrong fails the part instead of being saved as `done`. It also stops the board writer naming a grid of its
own. The lab that proved it is `lab/board_grid/` (free sweep over every stored board + run_001, 9 LOW calls, $0.436).
Every phase is offline ($0). Writing to the hosted project (phase 4 `--apply`) is the person's. Read this file whole,
then `lab/board_grid/grid.py`, `docs/scene_board/README.md` and `plan/2026-11-14/PLAN.md` §3.

## 0. Rules for the chat that builds this (read before anything)

- **Port the lab exactly.** `lab/board_grid/grid.py` (the cutter and the checks) and `run.py no_leak` go into the
  product unchanged: same constants, same steps. Never edit or re-run the lab to make the product pass. Every change
  beyond the lab is listed in §4 and marked **(not in the lab)**.
- **No paid call.** Nothing in this plan calls a model. Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **The board is never repainted by itself** (the person, 2026-11-13): a bad cut fails the part; a person presses the
  button that paints it again.
- **Two repos.** Backend: this repo (`.venv/Scripts/python.exe`, Python 3.12). Interface:
  `..\hiru-ai-studio-interface`. This plan expects NO interface change (§3.4); if one turns out to be needed, its
  `CLAUDE.md` and `AGENTS.md` are binding.
- **Heredocs mangle escapes**: write code with the Write or Edit tool. Read `git status` / `git diff` of a file before
  editing it (other plans' work is uncommitted). Never stash or reset the person's tree.

## 1. What goes wrong today

A board (or one part of it) is ONE picture of a grid of panels. `contracts.board.grid_for(n)` picks the grid
(`ceil(sqrt(n))` across), `board_prompt` asks for it, and `pictures.cell_boxes(png, n)` cuts it: for each line of the
grid asked for, it looks for a white gutter within `size / (parts * 6)` of the even split, and **where it finds none it
cuts at the even split, silently**. Nothing checks the crops; the part is saved `done` and its cells become the first
frames' panels.

Seen on 2026-11-22 (Love Hour, scene de75bc31, board part 2 of 2, `34683023`): 6 tall shots, asked 3 across and 2
down; the model painted 3 across and **3** down (two rows of panels, a row of empty cells). The cut at y = 768 ran
through the second row: shots 9-11 got their panel plus the top of the one below, shots 12-14 the bottom of their
panel plus an empty white cell.

Why the model painted another grid. **The prompt contradicts itself.** `writer_message` tells the board writer the
layout of the WHOLE scene (`grid_for(14)` = 4 x 4), and the writer copies it into `world`: "Paint one unified
storyboard image in a four-column, four-row grid ... fill the first fourteen cells and leave the final two cells
blank". `board_prompt` puts `world` into every part's prompt, so part 2 asked for 3 x 2 in its first sentence and
4 x 4 in its World paragraph. 15 of the 22 stored boards carry such a contradiction (lab sweep).

## 2. What the lab proved (`lab/board_grid/`, read `runs/sweep/report.md` and `runs/run_001/`)

- **Free sweep, every stored board** (`cut.py`; 22 cut, 6 skipped because Update board painted some of their panels
  alone): the product's cut is bad on **3** (34683023, 63817917, 72c07de3); the lab cutter cuts all 3 right and
  **breaks none** of the 19 the product cut right. Checked by eye (`runs/sweep/*_lab.png`).
- **Paid, run_001** (part 2 of the case above, 3 repeats each, LOW): **A** the saved prompt: 3/3 clean 3 x 2 (the fault
  is intermittent: 1 bad in 4 paints of this prompt). **B** the writer's layout sentences dropped (`no_leak`): 3/3
  clean. **C** a square grid with empty cells asked for: the model obeyed 3/3, but the panels shrink (340x765 ->
  340x510), a third of the sheet is wasted, and the product's cutter breaks on it. **The lab cutter cut 9/9 right.**
- So: the cutter is the proven fix. Dropping the writer's layout words removes a real contradiction, but 3 repeats
  cannot show it lowers the fault rate (hygiene, kept). The square grid is not adopted.

## 3. The design

### 3.1 The cutter reads the grid that was painted (lab `grid.cut`, `found_grid`, `_axis`)

Per axis: every THIN run of gutter-white lines (at most 2 % of the sheet) away from the sheet's edge is a gutter; a
wide white run is an empty cell or a drawn white card, never a gutter. The grid is the number of parts k whose even
splits, over the PAINTED extent (white margin under or beside the grid left out), explain every gutter found, with the
fewest splits left without a gutter; a tie goes to the grid asked for. A split with a gutter cuts at the gutter, one
without at the even split (panels painted touching, as today). Cells that are all white (>= 97 %) are empty cells, not
panels; the panels are the rest in reading order. When the found grid holds fewer panels than shots, the grid asked
for is cut as today, and the checks (3.2) judge it.

`pictures.cell_boxes(board_png, n)` keeps its name and signature and returns the lab's `cut(...)[0]`; the asked grid
is `grid_for(n)`, as now. Every caller (`paint`, `_store_part`, the locked-panel paste, the overlap panel) gets the new
boxes with no change of its own.

### 3.2 A bad cut fails the part (lab `grid.check`)

After cutting, each crop is checked:

| Check | Means |
|---|---|
| the crop is >= 97 % white | an empty cell was cut as a panel |
| a thin pure-white line (>= 99 %) runs across the crop, with paint on both sides | two panels in one crop |
| a thin gutter, or a white band >= 15 % at the crop's edge, beside paint | an empty cell inside the crop |

Any of these on any crop of a part → the part is saved `failed` with the error **"Part 2 of the board came out in a
different layout than was asked. Paint the board again."** (one part: "The board came out in a different layout ...");
the other parts still paint (as a failed part does today). The crops of a failed part are not stored as cells. The
lab's SHAPE check (panels far from the sheet's shape) is advice in the lab report only; it never fails a part
(**not in the lab** as a product rule: the lab only reported it).

### 3.3 The writer never names a grid

Two steps, both in `contracts/board.py`:
1. `board_prompt` drops the writer's layout sentences from `world` before it is used: the lab's `no_leak` rule, exactly
   (a sentence that matches `grid|columns?|across|down|cells?|panels? in shot order` AND
   `storyboard|panel|cell|grid`). `panel_prompt` keeps `panel_world` as today.
2. `writer_message` stops telling the writer the grid: "Write the storyboard: {n} panels, one per shot in shot order."
   without "laid out {cols} across and {rows} down" (**not in the lab**: the writer never needed it; code writes each
   panel's row and column in `board_prompt`). The writer's system prompt gains one rule in its Rules list: "`world` is
   the place, light and people for every panel. Never describe the sheet's layout (grid, rows, columns, cells, panel
   count, gutters): code lays out the sheet." (**not in the lab**; the agent's system prompt changes, so its cache
   resets once.)

### 3.4 Interface

None expected. The board card already shows a failed part's `error` (`scene-board-card.tsx`, the red chip) and offers
"Repaint whole board" when `whole` (a failed part makes it so). Phase 3 confirms this by a test on the API view; if the
card needs a change, it is listed there before it is made.

### 3.5 Mending the boards already stored (no model call)

`scripts/recut_boards.py`, DRY RUN by default: for every `done` board part whose painted cells all have a `box`
(a part with panels painted alone by Update board is skipped, as in the lab), it downloads the board picture, cuts it
with the new cutter, and runs the checks on the SAVED boxes and on the new ones. It reports each part where the saved
cut is bad and the new one is good (expected today: 3), each where both are bad, and, for each part to mend, the
first frames already painted from it (`first_frames.board_id` = the part, by shot).

With `--apply` (the person's, against the hosted project): for each part to mend, the new crops are stored at FRESH
paths (`cell_<NNN>-recut-<8 hex>.png`; storage paths are never overwritten, the thumbnail is made on upload), each
cell's `box` and `path` are replaced, its `pin`, `note`, `locked` and `previous` are kept (the old bad crop is NOT added
to `previous`: an undo must never bring it back), the numbered sheet is redrawn to a fresh path, and the row is written
once. An approved part loses its approval (D2). Audited as `board.recut`. Re-runnable: a mended part's saved cut passes
the checks, so a second run finds nothing.

## 4. Changes, file by file

**engine (`src/libs/hiru_ai/systems/frame_render/pictures.py`)**
- Port `lab/board_grid/grid.py` unchanged: the constants (`WHITE`, `LINE_WHITE`, `EMPTY`, `PURE_LINE`, `SOME_PAINT`,
  `EMPTY_PART`, `MAX_PARTS`, `THIN`), `_white_lines`, `_runs`, `_axis`, `white_share`, `found_grid`, `_inside`,
  `check`. `cell_boxes(board_png, n)` = the lab's `cut(board_png, n, grid_for(n))[0]`; the lab's fallback calls the
  old `cell_boxes`, which stays as the private `_even_boxes`. New `cut_problems(board_png, boxes) -> list[str]` = the
  lab's `check(...)[0]`.

**engine (`src/libs/hiru_ai/systems/frame_render/board.py`)**
- `paint()`: after `boxes = pics.cell_boxes(...)`, `problems = pics.cut_problems(image, boxes)`; if any, save the part
  `failed` with the §3.2 error and the problems in the log (never in the error text), keep `fields` (prompt, writer,
  colours) as today, `previous_last = None`, and go on to the next part.
- New const `BAD_CUT` (the §3.2 error, with the part number filled in).

**contracts (`src/libs/contracts/board.py`)**
- `board_layout_free(world: str) -> str`: the lab's `no_leak` rule on one paragraph. `board_prompt` uses
  `board_world(board_layout_free(writer.world), colours)`.
- `writer_message`: the grid words removed (§3.3).

**agent (`src/libs/hiru_ai/agents/board_writer/prompts/system.md`)**: the one rule of §3.3. Its agent test still
asserts the system prompt is the same with and without `edit` (plan/2026-11-17).

**script (`scripts/recut_boards.py`)**: §3.5, through `scripts/_common.py` `Rest`, with the engine's `pictures` for
cutting and `thumbs` for the thumbnails (as `backfill_thumbs.py` does).

**No schema change**: `scene_boards.cells` is jsonb with no check on its keys; `status = 'failed'` with an `error` is
already allowed for a part.

## 5. Phases

| # | What | Done when |
|---|---|---|
| 0 | lab fetch adds `writer` and `colours` to `input/love_p2/board.json` (read-only GET); copy as test fixtures, downscaled NOT allowed (gutters are 3-10 px): `tests/fixtures/board_grid/` gets the 3 bad stored boards and run_001 `A1`, `C3` PNGs + their saved boxes; if they are too big for the repo (> 3 MB in all), the parity test of phase 1 reads `lab/board_grid/` and skips when absent | fixtures in place |
| 1 | `pictures.py` (§4): tests in `tests/contracts/test_board.py` next to the old cutter tests: the old tests still pass; synthetic boards (asked 3x2 painted 3x3 with an empty row; asked 2x1 painted 1x2; panels touching; a white margin under the grid; a drawn white card in a panel) cut right; `cut_problems` flags the saved boxes of the 3 bad boards and passes the new ones; **parity**: for every board in `lab/board_grid/input/boards/` and `runs/run_001/`, product `cell_boxes` == lab `grid.cut` | tests green, `mypy` clean |
| 2 | `board.py` `paint()` (§4): tests with a fake painter returning a 3x3-painted picture for a 3x2 ask (cut right, part `done`), and one the cutter cannot mend (part `failed` with `BAD_CUT`, no cells stored, the next part still paints) | tests green |
| 3 | contracts + agent (§3.3): golden test: `board_prompt` on the fixture writer of `love_p2` equals `lab/board_grid/runs/run_001/B_prompt.txt` byte for byte (colours and labels as there); `writer_message` has no "across"/"down"; the agent test; `tests/api/test_boards.py` shows a failed part's `error` in the view | tests green |
| 4 | `scripts/recut_boards.py` (§3.5), dry run against the hosted project (read only): it lists the 3 parts and their first frames; tests with a fake `Rest` for apply (fresh paths, pin kept, `previous` untouched, approval cleared, re-run finds nothing) | dry run lists 34683023, 63817917, 72c07de3; tests green |
| 5 | docs: `docs/scene_board/README.md` (§ "after": the cutter and the bad-cut rule), `IMPLEMENTED.md`, the CLAUDE.md Scene board paragraph (a bad cut fails the part) | read through |
| 6 | **the person's**: `recut_boards.py --apply` on the hosted project; look at the 3 mended parts; approve; decide on any first frame painted from a bad panel (D3) | the person's yes |

Before finishing each phase: `ruff check src tests scripts`, `mypy`, `pytest -q`.

## 6. Decisions

- **D1 (open)**: a bad cut fails the part (the person paints it again) rather than repainting it by itself.
  Recommended: **fail it**: an automatic repaint is a paid call nobody pressed (the 2026-11-13 rule), and the lab
  cutter already mends every grid the model painted in the sweep and run_001.
- **D2 (open)**: a mended (re-cut) part that was approved loses its approval. Recommended: **yes**: its panels changed,
  so a person looks again (plan/2026-11-17 §3.3 does the same for Update board). The case board 34683023 is not
  approved, so this costs nothing there.
- **D3 (open)**: first frames already painted from a bad panel. Recommended: **list them only** (`recut_boards.py`
  names them); the person decides which to paint again. A re-cut does not mark them out of date (their pin did not
  move).
- **D4 (decided by the lab, the person's to overrule)**: the square grid (run_001 C) is not adopted.

## 7. Not in this plan

- Panels the wrong shape for the sheet (5-6 shots on a wide board come out square; 2 on a tall board wide): the lab
  sweep reports 6 boards. A grid that fits the panel shape is a separate change, and a paid lab, if the person wants it.
- Boards whose panels were painted alone by Update board (they have no grid to cut).
- Lowering the fault rate further (more lab repeats of A vs B); the cutter makes the fault harmless either way.
