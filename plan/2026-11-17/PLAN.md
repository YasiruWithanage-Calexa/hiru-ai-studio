# Scene board: an edited shot repaints only its own panel (plan/2026-11-17)

Revision 1 (2026-11-17). Nothing in this plan is built. It changes the Scene board (plan/2026-11-14,
`docs/scene_board/README.md`) so that adding, changing, deleting or reordering a shot, through Zora, Sable or by hand,
never repaints the whole board: the edited shot's panel is painted ON ITS OWN with its neighbouring panels as
references, and every other panel stays exactly as it is. The lab that proved it is `lab/panel_edit/` (run_001,
run_002, $0.485; read its `README.md`). Phases 0 to 5 are offline ($0); phase 6 is paid and is the person's. Read this
file whole, then `docs/scene_board/README.md` and `plan/2026-11-14/PLAN.md` §3.2-3.5.

## 0. Rules for the chat that builds this (read before anything)

- **Two repos.** Backend: this repo (`.venv/Scripts/python.exe`, Python 3.12). Interface:
  `..\hiru-ai-studio-interface` (Next.js 16; its `CLAUDE.md` and `AGENTS.md` are binding: data through
  `features/*/api.ts`, TanStack Query quiet by default, files through `<Media>`, **no costs in the UI**).
- **No paid call without the person's yes, each time.** Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **The board is never repainted by itself** (the person, 2026-11-13): an edit makes the board out of date; a person
  presses the button that updates it.
- **Approval stays per board part, as today** (the person, 2026-11-17): no per-panel approval.
- **Image rule**: boards and their panels at LOW (MEDIUM a setting), never HIGH. `gpt-image-2` `images.edit`.
- **Safe depiction**: every image prompt goes through `safe_depiction.blocking()` before the call.
- **Prompt hygiene**: a writer or image fault is fixed by a principle with examples from OTHER stories, never one
  scene's words.
- **Heredocs mangle escapes** (`\b`, `\n` became control characters in the lab): write code with the Write or Edit
  tool. Read `git status` / `git diff` of a file before editing it (other plans' work is uncommitted).

## 1. What and why

Today (`contracts/board.py` `Stale`, `systems/frame_render/board.py`, `routers/boards.py`):

| Edit | What the board says | What mends it |
|---|---|---|
| shot changed | "shot 4 changed" | "Repaint changed panels": a masked `images.edit` of the part's picture (D7 method A) |
| shot added / removed / reordered | `Stale.whole` | a whole repaint only: a new version, EVERY panel repainted, every approval gone |

So one added shot repaints panels nobody touched. And the lab showed the masked repaint is unsafe: **`gpt-image-2`
does not honour the mask** (run_001 `add_strip`: cells outside the mask became a different street; drift 29 of 255;
`change_mask` drift 6, every cell re-encoded). `repaint()` re-cuts EVERY cell from the model's picture
(`frame_render/board.py` around line 367), so today a "repaint shot 5" can silently change approved panels 1-4 and 6.
plan/2026-11-14 phase 0 (a) is answered: no.

## 2. What the lab proved (`lab/panel_edit/`, read its README)

- **One panel painted alone works** (`add_solo`, `change_solo`, `change_solo_b`, `first_solo`): the same mannequins,
  colours, finish, grade, props and landmarks as the board; the same input twice gave the same composition; the
  scene's first shot with ONE neighbour fits too.
- **The camera rule** (run_002 `CAMERA_RULE`) fixed the over-the-shoulder that run_001 missed.
- **The writer in one-panel mode** (product `system.md` + `lab/panel_edit/prompt/one_panel.md`): kept the fixed world,
  colours, props and landmark sides in all three edits; no conflicts; ~1,100-1,250 output tokens.
- **The board writer puts the SHEET's layout into `world`** ("six equal portrait panels ... gutters"): it contradicts a
  one-panel picture; the lab drops those sentences (`solo_world`).
- Faint lettering-like marks can appear at LOW (first_solo); the frame's vision check already looks for text.
- Measured: writer ≈ $0.02-0.03, one LOW panel ≈ $0.054-0.059 (costs never reach the interface).

## 3. The design

### 3.1 One action: "Update board"

The board card, when out of date, offers ONE button, **Update board**, and the API one route. It does everything the
edits need, in one job, for the scene's current board version:

| Out of date because | What the update does | Painted |
|---|---|---|
| a shot changed (its `plan_pin` moved) | paint that panel alone | 1 panel |
| a shot was added | write and paint its panel alone, insert its cell in shot order | 1 panel |
| a shot was removed | drop its cell | nothing |
| shots were reordered | reorder the cells | nothing |
| a shot became / stopped being a black plate | a black cell drawn by code / a painted panel alone | 0 or 1 |

Then code renumbers every cell AND every writer panel from the scene's shots as they stand (§3.5), redraws each part's
numbered sheet from the stored cells, and records it. A person can name some shots (`shots`) or none (= everything out
of date). **Repaint whole board** stays, as today, for a fresh look, for a board in the wrong shape (`wrong_shape`),
and when there is no board.

A **locked** panel is never repainted: if its shot changed, the update leaves it and the card says "shot 4 is locked
and out of date: unlock it to update it". An unlocked panel's **note** goes to the writer when that panel is painted
(as today).

### 3.2 Painting one panel (from `lab/panel_edit/run.py`)

1. **Writer, one-panel mode.** The SAME agent `board_writer`, the same system prompt byte for byte (cache): the
   one-panel instructions (`lab/panel_edit/prompt/one_panel.md`) go at the END of the user message, built by
   `contracts.board.writer_message(..., edit=...)`. The message carries the approved board's `world`, `geography` and
   panels as FIXED facts (a changed shot's old panel marked `being_replaced`), the shot's plan (`shot_plan`, as
   today), the mannequin note with the board's SAVED colours (§3.4), and the pictures: the place plate, the prop
   sheets, then the neighbouring panels ("panel N of the approved board, just before / after this one"; one at the
   scene's ends). The answer keeps today's schema; code takes `panels[0]` and ignores `world` / `geography` (the
   prompt asks for them empty). Several panels in one update = one writer call each (each sees the others as they
   stand, including panels painted earlier in the same update).
2. **Image.** `contracts.board.panel_prompt(writer, panel, labels, colours, aspect)`: the lab's `solo_prompt` (one
   film still filling the picture, no gutters; the neighbours attached last "sit next to this one on the same board:
   paint so it sits beside them unnoticed ... do not copy their framing"), `CAMERA_RULE`, `mannequin_line`, the
   world with its sheet sentences dropped (`panel_world`, the lab's `solo_world`), the geography, THE PANEL, `BODIES`,
   `NO_TEXT` without gutters. References: the place plate, the props the panel's plan names, the neighbouring panels
   (at most `MAX_IMAGE_REFS`). Size: the board's own shape (`aspect_of_board`), so the panel matches its neighbours.
   Quality: the board row's.
3. **Store.** The picture is the cell, whole (no crop): `<production>/boards/<board>/cell_<shot_id>-<job8>.png` (a
   fresh path, never overwritten; plus its `.thumb.webp` as every picture), `cell.source = "panel"` (grid cells are
   `"sheet"`), `cell.pin` = the shot's `plan_pin` now, `cell.box = None`. The old path goes to `cell.previous`
   (§3.6). The writer's panel for that shot is replaced in `scene_boards.writer` (`Writer.merged`).

No mask, no grid and nothing returned by the model is pasted over another panel: **a paint call returns one picture
and it becomes one cell.** The combined `storage_path` picture is no longer the source of any cell after an update;
it stays for history. The numbered sheet (`sheet_path`) is drawn by code from the cells (`pictures.scene_sheet` with
one cell size), so grid cells and panel cells sit side by side.

### 3.3 Approval

Per part, as today. The schema allows an approval only on a `done` part (`scene_boards_approved_done`), so when the
API queues the update it clears the touched parts' approval (as `/repaint` does today) and puts the approval it
cleared (`approved_at`, `approved_by`) in the job's state. While the job runs the parts are `queued` / `running`, so
`shot_panel` refuses a first frame from them. When the job writes a part: if a cell of that part changed, the part is
left unapproved and the card says "Updated: shot 5. Look at the board and approve it again."; if NO cell of that part
changed (a part next to the edit, or a failed panel), the job writes the person's own approval back. Until a changed
part is approved, no first frame of that part can be made (plan/2026-11-14 D3, unchanged).

Whether an update that paints NOTHING (only removed or reordered shots) clears the approval is **D2**.

### 3.4 Colours are the board's, not recomputed

`Board` today recomputes `colour_of` from the order people first appear, so an edit that adds a person to an earlier
shot shifts every colour, and a panel painted after it disagrees with its neighbours. New rule: the row's `colours`
(entity id → colour) win; a person who is not in them gets the first colour no one on the board uses
(`contracts.board.keep_colours(saved, people)`, pure); the merged map is written back. A whole repaint keeps today's
behaviour (fresh colours).

### 3.5 Numbers: cells and writer panels move together

The first frame reads its panel's words by NUMBER (`graph.py` `kit.frame_sections(writer, int(cell["number"]), ...)`),
and `Writer.panel(number)` keys by number. After an add or a delete, shots are renumbered. So the update's last pure
step, `contracts.board.renumber(cells, writer, shots)`, sets every cell's `number` from its `shot_id` and every writer
panel's `shot` from the same map, in ONE write of the row. A test holds it: for every painted cell, `writer.panel(
cell.number)` is the panel written for that shot id.

Parts: an added shot joins the part that holds the shot before it (the first part for a new shot 1). A part may grow
past `PART_SIZE`: the limit was for painting a grid, and an updated part is never painted as a grid. The overlap
panel (a part's last panel repeated as the next part's first) is ONE shot in two parts' cells: an update writes both
and clears both approvals.

### 3.6 Undo is free

Zora's undo (a `scene_plan_revisions` row) puts a shot's plan back, so its pin goes back to the old one. Each cell
keeps `previous: [{pin, path, panel}]` (at most 3). When the shot's current pin equals one in `previous`, the update
restores that picture and writer panel with no model call.

### 3.7 A Zora or Sable save must not make untouched shots "changed"

`jonathan_write` rewrites every shot of the scene (`replace_shots`) and rebuilds each shot's IR from the whole scene
(`rows_for` ~line 219, `design_all` ~line 279); a shot with no blocks takes its `block_start` from the shot before
it. If any of that moves the `plan_pin` of a shot nobody touched, the board would ask to repaint it. Phase 0 tests it
on a stored Jonathan plan: apply one op through Zora's turn code (fake author), save through `jonathan_write`, and
assert that every untouched shot's `plan_pin` is equal. If one moves: fix the cause (keep an untouched shot's row as it
was), or narrow `plan_pin` to what the panel shows (`_PIN_IR` / `_PIN_INTENT`), whichever the test points at. Sable
hands plan edits to Zora, so this covers both. Other planners (David, Raphael, the classic chat) are out of scope: the
update works for them, only their pins are not tested here.

## 4. Changes, file by file

**contracts (pure, `src/libs/contracts/board.py`)**
- `Stale`: `whole` becomes "only a whole repaint can mend it" = no current board or `wrong_shape`; added, removed and
  reordered shots are listed for the update. New `Stale.paint` (shot ids that need a panel) and `Stale.tidy` (cells
  to drop or move).
- `writer_message(..., edit=Edit | None)`: the one-panel instructions and the fixed board at the end of the message.
- `panel_prompt`, `CAMERA_RULE`, `panel_world` (sheet sentences dropped), `keep_colours`, `renumber`,
  `insert_position(cells, shots, shot_id)`, `previous_for(cell, pin)`.
- Remove `repaint_prompt` and its tests (masked method gone, D3).

**engine (`src/libs/hiru_ai/systems/frame_render/board.py`, `pictures.py`)**
- `update(ctx, production, world, rows, state, job_id, warn)` replaces `repaint()`: claim the parts, `keep_colours`,
  for each shot to paint: `previous_for` or writer → `panel_prompt` → `blocking` → painter → store (§3.2); drop and
  reorder cells; `renumber`; redraw each touched part's sheet; write each part once (cells, writer, colours,
  `sheet_path`, `status = done`; the saved approval written back only if none of its cells changed, §3.3). A failed panel keeps its old cell (a changed shot) or stays out
  of date (an added shot); the others still update; the job reports `partial` with the reason per shot.
- `run()`: `state.update` → `update()`. The `state.repaint` branch is removed.
- `pictures.scene_sheet`: cells of different sizes drawn at one size (fit, not stretch).
- `Board`: takes the saved colours (§3.4).

**agent** (`agents/board_writer/`): no new agent (rule 8). `evals/cases.yaml` gains a one-panel case (the lab's
add, with a fake answer); the agent test asserts the system prompt is unchanged by `edit`.

**API (`src/api/routers/boards.py`, `src/api/services/boards.py`)**
- `POST .../scenes/{scene_id}/board/update` `{shots?: [shot_id]}` → 202 `BoardStarted`: refuses when there is no done
  board (409, "Paint the board first"), when `wrong_shape` (409, "Repaint the whole board"), when nothing is out of
  date (409), when a plan or build runs (`task_manager.refuse_busy`). Sets the touched parts `queued` with their
  approval cleared (the schema's `scene_boards_approved_done`), dispatches `JobKind.FRAME_RENDER` with
  `state={"update": true, "scene_id", "board_ids", "shots", "approvals": {board_id: {approved_at, approved_by}}}`,
  audits `board.update`. A dispatch failure puts the parts back to `done` with their approval.
- `POST .../scene-boards/{id}/repaint` is removed (the interface moves to `update` in the same phase).
- `board_view`: `whole` per the new `Stale`; new `update` list (shot numbers and what happens to each:
  `changed | added | removed | moved | locked`); `NOT_ON_BOARD` says "Update the board"; cells carry no storage path
  (as today: `media_links`).

**interface (`..\hiru-ai-studio-interface\src\features\production\`)**
- `lib/board.ts`: the view's `update` list; `whole` meaning as above.
- `components/scene-board-card.tsx`: out of date → "Shot 5 changed · shot 4 added · shot 7 removed" and **Update
  board** (`client.ts` → the new route); "Repaint whole board" stays as a secondary action; after an update, "Look at
  the board and approve it again". Locked-and-changed shots named with "unlock to update".
- `components/scene-board-dialog.tsx`: per-panel "Update this panel" replaces "Repaint panel".
- Tests: `scene-board-card.test.tsx` for each state.

**No schema change** (checked 2026-11-17 against `Database/schema_v26.sql`): `scene_boards.cells`, `writer` and
`colours` are jsonb with no check on their keys; `source` and `previous` are new keys in a cell. The one constraint
that shapes the design is `scene_boards_approved_done` (§3.3).

## 5. Phases

| # | What | Done when |
|---|---|---|
| 0 | §3.7: the Zora pin test (`tests/zora/test_board_pins.py`) and its fix if it fails | untouched shots keep their pins after a Zora save; `pytest -q` green |
| 1 | contracts: §4 contracts list, with tests (`tests/contracts/test_board.py`): renumber holds writer and cells together, keep_colours, insert_position, previous_for, the new `Stale`, `panel_prompt` matches the lab's run_002 prompt for the same input (golden file from `lab/panel_edit/runs/run_002/add_solo_prompt.txt`, colours and labels as there) | tests green |
| 2 | engine: `update()`, `scene_sheet`, `Board` colours; remove `repaint()`; tests with fake writer and painter: a changed shot paints ONE picture and no other cell's path or bytes change; an add inserts and renumbers; a delete paints nothing; a locked shot is left; a failed panel keeps the old cell; undo restores without a call; the overlap panel updates both parts | tests green, `mypy` clean |
| 3 | API: the route, the view, removal of `/repaint`; `tests/api/test_boards.py` | tests green |
| 4 | interface: card, dialog, client, tests | `npm test`, `npm run lint`, `tsc` green |
| 5 | docs: `docs/scene_board/README.md` (§ "Approve, out of date, repaint" rewritten), `IMPLEMENTED.md`, the CLAUDE.md Scene board paragraph ("a board is never repainted by itself" stays; "an edited shot repaints only its own panel" added) | read through |
| 6 | **paid, the person's**: on a real scene with an approved board, one Zora edit (change), one added shot, one deleted shot → Update board → look → approve → one first frame (MEDIUM) from the new panel. About $0.15 for the panels and writer, plus the frame | the person's yes to keep it |

Before finishing each phase: `ruff check src tests scripts`, `mypy`, `pytest -q` (interface: its own checks).

## 6. Decisions

- **D1 (the person, 2026-11-17)**: an edited, added, deleted or reordered shot never repaints the whole board; only
  its own panel is painted, alone, with the neighbouring panels as references; other panels are never touched.
- **D2 (open)**: an update that paints nothing (only removed or reordered shots) keeps the approval? Recommended:
  **keep it**: no picture changed. (Clearing it blocks every first frame of the part for no change on the board.)
- **D3 (the person, 2026-11-17, replaces plan/2026-11-14 D7)**: the masked repaint is removed: the image model does
  not honour the mask (lab run_001).
- **D4 (the person, 2026-11-17)**: approval stays per part, as today.
- **D5 (open)**: the update stays a person's button (the 2026-11-13 rule). Recommended: **yes**. The alternative, an
  automatic update after a Zora or Sable save, would spend without a click and break that rule.

## 7. Not in this plan

- Per-panel approval (D4).
- Repainting a whole board in panels (a new board is still one grid picture, as the lab of 2026-11-13 proved).
- Making a panel's first frame stale when its panel changes: already so (`first_frames.board_id` + the cell's pin).
- Pins for planners other than Jonathan (§3.7).
