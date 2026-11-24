# Fixed marks: what is built (plan/2026-11-24d)

Nothing is built yet. The lab is `lab/fixed_marks` (`FINDINGS.md`, $0.611 of $0.75 spent).

| phase | status |
|---|---|
| 0 lab: the next parts and a walk (paid, the person's yes) | done 2026-11-24, $0.188: R_001, W_001; §3.3 changed (three panel lines, anchors) |
| 1 `contracts/marks.py` | done 2026-11-24 (offline, no paid call) |
| 2 the board writer | done 2026-11-24 |
| 3 the paint loop | done 2026-11-24 |
| 4 the API (no schema change, see below) | done 2026-11-24 |
| 5 the interface | done 2026-11-24 |
| 6 live check (the person's) | not started |

Decisions D1 to D5 (PLAN.md §5): accepted as recommended by the person, 2026-11-24.

## Phase 1 (2026-11-24)

Built: `src/libs/contracts/marks.py` (new, pure) and additions to `src/libs/contracts/board.py`; tests
`tests/contracts/test_marks.py` (21). Nothing calls them yet (phase 3 wires the paint loop).

- `marks.stretches(staging, items, shots, to_whole=, seen=, painted=)` → `Blocking` (the stretches, each shot's
  stretch, who moves during each shot). Moves: a zone change, `walking` / `running` (and the arrival after it), an
  implied `move:<who>` step, an entrance after block 0, an exit to `off`. A posture change alone keeps the stretch (D1).
  A shot belongs to the stretch of its opening block. `Stretch.plate` is true only with someone still in two or more
  painted shots.
- `marks.whole_index(items)` maps a line-parts scene's item numbers to whole blocks (the map's numbering).
- `marks.check` (one spot per person per stretch, the first; the rest dropped; a `conflicts` line per missing spot),
  `complete`, `of_stretch`, `paragraph` (the lab's words), `panel_line` (still / leaves the mark in this shot / a new
  stretch begins), `plate_view`, `plate_label`, `plate_job`, `pin`, `GroundMark` (the writer's wire shape, for phase 2).
- `board.board_prompt(..., marks=, panel_marks=)` and `board.panel_prompt(..., marks=, panel_mark=)`: the paragraphs
  after Geography, the line at the head of each panel; without them a prompt is byte for byte as before (tested).
  `board.board_job` gives the plate's job; `board.plate_prompt` is the plate's prompt.

Deviations from the plan, and why:
- **`plate_prompt` is in `contracts/board.py`, not `marks.py`**: it is built from the board's own paragraphs
  (`mannequin_line`, `prop_line`, `views_paragraph`, `hands_text`), and `board.py` imports `marks` for the plate's job,
  so the other way would be an import cycle.
- **A map is not refused for being "stale"** (§3.1 said a stale map gives no stretches): the breakdown writes maps with
  an empty `basis` (scene 4's), which `SceneStaging.stale` always calls stale. As `board.marks_at` already does, a map
  with no basis is read by block number; a map with a basis written for another script is read through its anchors,
  and a mark whose block is gone is left out.
- **Words changed from the lab** (listed in the module's docstring): the gap sentence drops the lab scene's own
  distance (the writer's `apart` gives it); a seated or kneeling person "sits" / "kneels"; the move line uses no
  pronoun ("leaves that mark in this shot"); the plate's words are split into its label and its job; the plate's
  camera sentence is the view's own `camera` words and its hands are `hands_text` of the stretch's first panel.
- **A one-shot stretch's line** is "Marks: on the ground marks of shot 16." (the lab's "the same gap as in every panel
  of them" does not read for one panel).

Found, not changed (for the person): `board.shot_context` reads each shot's stager marks with `marks_at(marks,
shot.block_start)`, but on a scene planned with line parts the shot's block counts the parts and the map counts whole
blocks, so a later shot can read a mark meant for a later block (scene 4: shots 11-14 open at "blocks" 19-22 of a
19-block script). Phase 3 can pass `whole_index` there too; it is today's behaviour, so it waits for the person's yes.

Checks: `ruff check` clean on the new and changed files (5 long lines remain in files this phase did not touch:
`scripts/canon_refine_live.py`, `contracts/breakdown/checks.py`, `raphael_write/logic.py`, `tests/api/test_production.py`,
`tests/contracts/test_canon.py`); `mypy` clean (1174 files); `tests/contracts` 834 passed.


## Phase 2: the board writer (2026-11-24)

- `contracts.board.writer_bundle(..., stretches=)` and `marks.stretch_rows`: the writer reads each stretch's number,
  shots, `still`, `on_the_move` and what ends it ("Anudi moves before shot 3").
- `agents/board_writer/schema.py`: `Output.marks: list[GroundMark]` (`stretch`, `who`, `spot`, `apart`).
- `prompts/system.md`: the GROUND MARKS rule (one spot per stretch and still person, landmarks as the pictures show
  them, a closer or turned camera never moves anyone, a walk the map missed is kept and said in `conflicts`), examples
  from other stories (a jetty, a shop counter), and one sentence on `marks` in the closing paragraph.
- `contracts.board.Writer` carries `marks` and `plates` through every rebuild (`of`, `dump`, `merged`, `renumber`,
  `reuse_writer`, the system's `_with_panel` and black plates); an old board dumps exactly as before.
- Eval case "ground marks for a stretch of two still people"; tests in the agent folder and `tests/contracts/test_marks.py`.

## Phase 3: the paint loop (2026-11-24)

`systems/frame_render/board.py`:
- `Board.blocking` (the stretches, through `whole_index` for a line-parts scene), `check_marks` (the spots kept; missing
  ones, and "No staging map: the people's spots are not held between shots.", in `conflicts`), `ground_words`,
  `panel_marks`, `views_template` (a sheet made before plan/2026-11-24c counts as `outside`).
- `_paint_plates` before the parts: one plate per stretch with `Stretch.plate` and a complete set of spots, kept when
  its pin matches a saved plate and it is not in `state.repaint_plates`; `_check_plate` (`board_inspector` with the
  first panel's hands and the plate's view, painted again once on a fault, `fix_line` appended); stored at
  `<production>/boards/<board>/plate_<n>-<id>.png`. Any failure leaves the words only and a `conflicts` line; a plate
  never fails the board.
- Parts: the plates of their stretches after the place and vehicle pictures and before the overlap panel; the ground
  paragraphs and panel lines in `board_prompt`. `_mend` and Update board's `_paint_panel` pass the words and the
  stretch's plate (an update reads the saved plate by shot id).
- Tests: `tests/hiru_ai/test_board_marks.py` (6): plate first and attached, no map, a missing spot, a repaint keeps the
  plate and Repaint marks paints it again (a new path), a refused plate, a panel painted alone.

## Phase 4: the API, without schema v31 (2026-11-24)

**Deviation: no migration.** `save_board` patches columns directly, so a `scene_boards.plates` column that is not
applied would fail every board part on a database without it. The plates belong to the version, as the words do, so
they live in `writer.plates` beside `writer.marks` (every part stores the same `writer`; the API never sends `writer`
to a browser). No `Database/schema_v31.sql`, no upgrade file, nothing for the person to apply.

`routers/boards.py`: `SceneBoardView.plates` (`BoardPlateView`: `n`, `shots`, `label`, `marks` in words, `url` /
`thumb_url` / `file_key` tickets, the check's `problems`, `stale`). `plate_views` rebuilds the stretches from the
scene's staging map and lines and marks a plate stale when its shots or still people changed, adding "The marks of
shots 1 to 14 changed: Rewrite and repaint." to `stale_reasons` (advice; the board's state is unchanged). `POST
.../scenes/{id}/board/plates/{n}/repaint` (CanGenerate; 404 for an unknown plate) starts the same job as a repaint
with `state.repaint_plates = [n]`, at the board's quality, from the saved words; it and `paint_board` share `_start`.
Tests in `tests/api/test_boards.py` (2): plates by ticket, no path or prompt in the response, stale on a new walk;
Repaint marks' state, 404, 403 for a reviewer.

## Phase 5: the interface (2026-11-24, `hiru-ai-studio-interface`)

- `lib/board.ts`: `ApiBoardPlate`, `BoardPlate`, `SceneBoard.plates` (absent from older servers = []).
- `client.ts`: `repaintBoardPlate(productionId, sceneId, n)`.
- `scene-board-card.tsx`: a **Marks** row above the panels when there are plates: each plate's picture (`<Media>` with
  its thumb), "Shots 1 to 14", each person's spot in words, what the check still sees, "Marks changed" when stale, and
  **Repaint marks** (`onRepaintMarks`, wired in `production-workspace.tsx` and `scene-board-dialog.tsx` like Update
  board). No costs.
- Tests: two in `scene-board-card.test.tsx` (the row, its words and button; no row without plates).

## Checks (2026-11-24)

- Backend: `ruff` clean on every file this plan touched; `mypy` clean (1174 files); `tests/contracts` (with
  `test_marks.py`), the board system tests, the board writer's tests and `tests/api/test_boards.py` pass.
- Failing, and failing the same on a clean HEAD (checked in a throwaway worktree), so not this plan's: 8 API tests
  (6 expect `localhost:8000` where the local `.env` says 8001; `test_scene_canon` cast marks; `test_looks` draft
  return), 3 parity tests (`canon_extract/model_cards`, `structure_build/prose_model*`), and `hiru-ai validate`'s 3
  stray folders (`steps/prompt_polish`, `agents/prompt_writer`: only `__pycache__` left of removed parts; `steps/zora`).
  The stray folders are the person's to delete.
- Interface: `tsc` and `eslint` clean; the card's tests pass (16); one other test fails (`raphael-panel.test.tsx`, the
  length caps list), outside this plan. The six changed files were formatted with Prettier (two of them hold the
  person's own uncommitted work: formatting only). `format:check` still reports 358 other files repo-wide.
- No schema change, so `supabase test db` and the advisors have nothing new to check.

## For the person (phase 6)

1. Paint scene 4's board with Rewrite and repaint (the writer must write the spots): one plate for its still shots,
   then the parts; compare with v18 and the lab's T_001 / R_001 / W_001.
2. Paint a scene with a walk in the middle, and one with a shot / reverse across the line (untested in the lab).
3. Look at the plate before approving: what it shows goes into every panel of its shots.
4. Decide on `board.shot_context`'s block numbers on line-parts scenes (phase 1, "Found, not changed").

## After the build: Rewrite and repaint for an older board (2026-11-24, the person)

A board written before fixed marks had "Rewrite and repaint" disabled (it turned on only when a shot changed), so
it could never get spots. `SceneBoardView.marks_needed` (`marks_missing`: the saved words hold no spot while the
staging map has a stretch of two or more shots with someone still) now turns it on, with a line that says why;
"Repaint whole board" stays allowed (it paints the old words again). Tests: one API, one card.

## Board v20: the marks never switched on (2026-11-24, the person)

v20 (Rewrite and repaint) was painted with no Ground marks paragraph, no marks line and no plate in any of its three
parts (`lab/fixed_marks/dump_board.py 20` saves each part's prompt and pictures in `lab/fixed_marks/board_v20/`: the
location sheet, the vehicle sheet and the overlap panel, nothing else). The writer gave Kasun's spot ("... 1.4 metres to
Anudi's left") and not Anudi's; `marks.complete` asked for EVERY spot, so one missing spot switched the stretch off
and only a conflicts line said so. Fixed: one spot holds the stretch (words and plate), a person without one is told
to keep one spot too, the conflict says the writer left it out; the writer's prompt now says EVERY name in `still`,
the first included; `clean_spot` takes off the writer's own leading verb ("Kasun stands Standing on ..."). v20's saved
words now give the paragraph and a plate for shots 1 to 13, so Repaint whole board (no writer call) is enough.

## The plate is internal (2026-11-25, the person)

"This image is internal: we generate it but we don't expose it on the frontend." `SceneBoardView` no longer has
`plates` (`BoardPlateView` removed); `plate_reasons` keeps only the stale line ("The marks of shots 1 to 13 changed:
Rewrite and repaint."). The interface's Marks row, `PlateTile`, `BoardPlate` types, `repaintBoardPlate` and
`onRepaintMarks` are removed; the card's words no longer name the plate. The repaint route stays, with no button.
Tests: the API test now checks that no plate, ticket, prompt or spot is in the board view.
