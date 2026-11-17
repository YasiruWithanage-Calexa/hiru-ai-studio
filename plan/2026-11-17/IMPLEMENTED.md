# plan/2026-11-17: what is built

Phases 0 to 5 built offline on 2026-11-17 (both repos, uncommitted), no paid call. The lab: `lab/panel_edit/` (run_001,
run_002; $0.485 booked), read its `README.md`. Phase 6 (paid, live) is the person's.

| Phase | State |
|---|---|
| 0 Zora pin test | built: `tests/zora/test_board_pins.py`; passed with no fix needed |
| 1 contracts | built: `contracts/board.py`, `tests/contracts/test_board_update.py` (golden = run_002 `add_solo` prompt, byte for byte) |
| 2 engine | built: `frame_render/board.py` `update()`, `pictures.scene_sheet`, `Board` colours, `repaint()` removed; `tests/hiru_ai/test_board_update.py` |
| 3 API | built: `POST .../scenes/{id}/board/update`, the view's `update` list, `/repaint` removed; `tests/api/test_boards.py` |
| 4 interface | built: card, dialog, client, `lib/board.ts`; `scene-board-card.test.tsx` |
| 5 docs | built: `docs/scene_board/README.md` (§ "Approve, out of date, update"), `CLAUDE.md` Scene board paragraph, this file |
| 6 paid live check | run 2026-11-17 with the person's yes: worked, $0.31 (see below); keeping it is the person's call |

## Phase 0: what the test found

Zora and Sable no longer save through `jonathan_write` (the plan's §3.7 path): since plan/2026-11-13 phase 8 both save
through `core.coverage_rows.Saver`, which copies an untouched row as it was and only renumbers it (`plan_pin` leaves
the number out). The test applies a change, an insert and a removal through Zora's turn code with recorded answers
(the removal and the insert come back as a confirm card; the test accepts it) on the lab's Raphael scene, and asserts
every untouched shot keeps its pin, and that undo gives the edited shot its old pin back. All four passed: **no fix was
needed**. A removal moves the pins of the shots that take over the removed shot's lines (they really changed; the test
checks only a shot whose version moved can change its pin).

## Built, file by file

**Backend (`hiru-ai-studio`)**
- `src/libs/contracts/board.py`: `Stale` rewritten (`whole` set by the caller; `paint`, `tidy`, `moved`, `locked`,
  `items()`, `updatable`); every cell pinned, a black plate too (older boards' plates carry no pin and are not flagged);
  `new_cell(..., source)`; `Edit`, `ONE_PANEL`, `writer_message(..., edit=)`, `panel_answer`, `writer_neighbour_label`;
  `panel_prompt`, `CAMERA_RULE`, `NEIGHBOURS`, `neighbour_label`, `panel_world`; `keep_colours`, `renumber`,
  `insert_position`, `previous_for`, `remember`, `panel_of`; `repaint_prompt` removed.
- `src/libs/hiru_ai/systems/frame_render/board.py`: `update()` + `_run_update()` replace `repaint()`; `Board(saved=)`
  keeps the board's colours; each cell painted by the latest update carries `fresh`. `pictures.py`: `repaint_mask`
  removed; `scene_sheet` fits cells of different sizes into one cell size. `graph.py`: routes `state.update`, event
  "Scene board updated", audit `board.update`.
- `agents/board_writer`: no new agent; `evals/cases.yaml` + one-panel case; the test asserts the system prompt is
  unchanged by one-panel mode.
- `src/api/routers/boards.py`: `POST .../scenes/{scene_id}/board/update` `{shots?: [shot_id]}` (409: no finished board
  or a failed part "Paint the board first", wrong shape "Repaint the whole board", nothing out of date, a plan or a
  build running; every part queued with its approval cleared and carried in `state.approvals`; a dispatch failure puts
  the parts back `done` with their approval); `/scene-boards/{id}/repaint` removed; the view gains `update` and each
  cell `fresh`; `whole` = no finished board, a failed part, or the wrong shape. `services/boards.py`: `updatable`,
  `PAINT_FIRST`, `WRONG_SHAPE`, the `NOT_ON_BOARD` and `STALE` words say "Update the board".
- `src/api/workers/sweeper.py`: a stuck board part that still has its cells goes back to `done` (its old picture in
  force) instead of `failed`.
- `lab/panel_edit/run.py`: keeps its own copies of the removed `repaint_prompt` / `repaint_mask`, so run_001's masked
  calls can still be read and dry-run.

**Interface (`hiru-ai-studio-interface`)**
- `lib/board.ts`: `update` list, cell `fresh`, `updateSummary`, `shotsPhrase`. `client.ts`: `updateSceneBoard`
  replaces `repaintBoardPanels`.
- `scene-board-card.tsx`: out of date → "Out of date: Shot 5 changed · shot 4 added · shot 7 removed" and **Update
  board**; a locked and changed shot named ("unlock it to update it"); "Repaint whole board" stays; after an update,
  "Updated: shot 5. Look at the board and approve it again."; the panel dialog's **Update this panel** replaces "Repaint
  this panel". `scene-board-dialog.tsx` and `production-workspace.tsx` call the new route.

## Choices made while building (read them)

- **D2 taken as recommended**: an update that paints nothing (only removed or moved shots) keeps the approval.
- **D5 taken as recommended**: the update stays a person's button.
- Every part of the current version is queued by an update (a renumber can touch every part), and a part none of
  whose cells got a new picture gets its approval back.
- The tidy step (drop removed cells, put moved cells in order, renumber) always runs; the `shots` filter narrows only
  what is painted.
- A one-panel writer message carries the fixed board, the plan, the pictures and the mannequin note, as the lab did,
  not the scene bundle; the panels are numbered as the scene's shots stand now (the lab kept the old numbers).
- The writer gets `PANEL_WRITER_MAX_OUTPUT` = 6,000 tokens (the lab's ceiling), not the board's 10,000.
- A panel painted alone is stored with `panel: 1`, `box: None`, `source: "panel"`.

## Checks (2026-11-17)

Backend: `ruff check src tests scripts` (4 errors, the same 4 as on main, none in files changed here), `mypy` clean,
`pytest -q`: 5,782 passed, 48 failed. Every failing test file (adam system and removal, api handoff / looks /
production / scene_canon / thumbs, david / jonathan / raphael / zora removal, raphael api and checks, frame_render
system, parity, shot_producer, reader ingest) was run again on an untouched worktree of main with the same `.env`:
the same tests fail there. None of the failures comes from this plan; every board test passes. Interface: `npm run lint` (1 warning, already on main, not in these files),
`npm run typecheck` clean, `npm test` 484 of 485 (the 1 failure is `raphael-panel.test.tsx`, already failing on main),
`prettier --check` clean for every file changed here (the repo has 92 other files already unformatted).

## Phase 6: the live check (2026-11-17, the person's yes)

`scripts/board_update_live.py`, files in `lab/panel_edit/runs/live_20261117/` (backup `before.json`, `state.json`,
`look/`, the frame). Scene: Love Hour 4, scene 3 (`bd5a6483`), vertical, 5 shots, board v5 approved.

- **Edits** through the shared row save (`coverage_rows.Saver`, as Zora and Sable), one revision each (2, 3, 4; Zora's
  undo reverts them): shot 3 to a low curb-height angle, 24mm; a new INSERT after it (the phone in Kasun's hand, rain on
  the screen); shot 2 (the classic planner's wide of the phone falling) removed. Each save touched only its own shot.
- **Update board**, first try: the script's context had no painter, so both panels failed with "Image generation is not
  set up"; the failure path behaved as designed: the removed cell dropped, the rest renumbered, nothing painted, the
  approval written back (D2). Second try: 2 one-panel writer calls + 2 LOW pictures, 138 s, **$0.17**; `updated: [2, 3]`;
  nothing out of date after it; each writer panel follows its own shot after the renumber; shots 1, 4, 5 untouched.
- **Look**: both new panels sit among the old ones (same red mannequin, dark-green three-wheeler, wet pavement and
  drain, orange phone). The writer caught a wrong detail in the test's own text ("maroon bodywork", carried over from
  the lab's scene), kept the board's dark green and said so in `conflicts`, as `ONE_PANEL` asks.
- **Approve** (as the API's approve), then **one MEDIUM first frame of shot 2** from its new panel: done, vision check
  "Frame matches the shot", **$0.14**. Kasun real, in his own clothes, where the panel put him, the phone at his feet.
- **Total $0.31** (prices over-stated as in the labs).

Found and fixed: the out-of-date line said "shot 2 changed · shot 3 added · shot 2 removed" (the removed one is the
board's old number); it now says "the board's shot 2 removed" (backend `Stale.reasons`, interface `updateSummary`).

Seen, not fixed: on the numbered sheet a panel painted alone is a true 9:16 while cells cut from the old grid are
narrower, so the new panels are drawn with dark bars above and below (fit, never stretched). Cosmetic: the cells
themselves are whole.

The scene now holds these edits, the updated approved board and the new frame. To put the scene back, undo three times
in the scene's Zora chat (the board then shows shots 2, 3 changed / added again; Update board restores shot 3's old
panel for free from `previous`, the removed shot comes back as added and is painted alone).

## Found in the product (2026-11-17, Scene 4, a person's Update board)

The live check called the engine directly, so it missed two faults on the real path:
- **The update never reached the board engine.** The frame_render handler sends board work to the `hiru_ai` graph
  whatever `AI_ENGINE` says only for `board_id`, a face sheet, `from_board` or `quality` (`graph_only`); `update` was
  missing, so under `AI_ENGINE=legacy` the job ran the legacy pipeline, found no frames, ended `done` in a second and
  left both parts running. Fixed: `graph_only` includes `update`; test in `tests/services/frame_render/test_frame_render.py`.
- **The sweeper failed parts that still had their picture.** `scene_boards.active_before` selected only
  `id,job_id,updated_at`, so `cells`/`sheet_path` were never seen. Fixed: it selects both.
- Scene 4's board v5 (both parts, untouched by the job) was set back to `done` by hand; nothing repainted.

## Open

- Keep the phase 6 edits or undo them (the person's).
- The interface was not looked at in a browser.
- Pins are tested for Zora and Sable only (§3.7); other planners are out of scope.
