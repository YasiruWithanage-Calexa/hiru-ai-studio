# plan/2026-11-23c: what is built

Built offline on 2026-11-23, both repos, uncommitted. **No paid call was made.** The person asked to "implement the
plan" right after answering Q6, so the paid lab (§4, runs B-D) was not run first, as §0 asked. The product code is
built instead, and the lab's question is answered by the live check below, which is the person's.

## Phase 0 (free read): done

Recorded in PLAN.md §3.6: the plan was clean; the umbrella came from Anudi's `scene_looks.condition`; the writer DID
name the hands and the painter ignored them; the stager's hands were empty and `intent.opens` was missing on all 14
shots.

**F3, the cause:** this scene's `scenes.staging` has `basis: ""`. `SceneStaging.placed` resolves every mark through
the basis, so with an empty one nothing is placed, `states_of` gives an empty state and `raphael_write` writes no
`opens`. The board no longer depends on it (it reads marks by block number, `contracts.board.marks_at`). The ledger
itself is **not** changed here: which stager wrote a map with no basis (the breakdown stager at creation, or an older
map) is for a separate fix.

## Built

| Plan | Where |
|---|---|
| §3.1 bundle | `contracts/board.py`: `shot_plan` (beats with performance and camera, `opening_state`), `marks_at`, `props_at`, `clip_of`, `breakdown_of`, `shot_context`, `board_shots(..., names)`, `writer_bundle` (whole geography, colour script, key image, zones, every mark field, props set down). `frame_render/board.py`: names for who is only heard, gender and age per person |
| §3.2 writer | `agents/board_writer/prompts/system.md` (six new rules, examples from other stories), `schema.py` (`left_hand`, `right_hand`, `props[]`), `contracts.board.PanelPerson`, `PanelProp`, `Panel.props`, `panel_dump`; old boards load and are stored as they were |
| F1 | the writer rule "what is held comes from the plan" + `writer_findings` reports a held thing no plan of the shot gives |
| §3.3 stand-ins (D2, D4, D5) | `prop_line`, `SUPPORT`, `hands_text` in `board_prompt` / `panel_prompt`; `mannequin_line` no longer calls props real; the board picture gets the location plate only (`Board.image_pictures`), the writer still reads the prop sheets; props matched by name, alias or word ending (`holding.canon_match`: "smartphone" is the canon "phone"); first frame: `PROP_STAND_INS`, `unprop`; `frame_inspector` looks for a leftover clay object |
| §3.4 check | `writer_findings` (into `conflicts`, both the whole board and a panel painted alone) |
| F2 board check | new agent `agents/board_inspector` (tier `vision`); `frame_render/board.py` `_check_panel`, `_faults`, `_mend`: a failed panel painted again alone once with `fix_line`; `cell.check = {ok, problems, fixed?, repainted?}`; still wrong → a conflict line; the part's sheet redrawn. Also after a panel painted by Update board. Off without `OPENAI__MODEL_VISION` |
| D6 | `ONE_IMAGE_TALL = PART_SIZE_TALL = 6` |
| D7 | `plan_pin` = `v2:<hash>` (also reads `opens`, `heard_only`), `legacy_pin`, `pin_matches`; `stale_cells`, `api/services/boards.py`, undo (`previous_for` with the old pin) |
| docs | `docs/scene_board/README.md`, `docs/AI_CATALOG.md` (regenerated) |
| interface | `scene-board-card.tsx`, `scene-board-dialog.tsx`: "the props as white clay stand-ins" |

## Tests

New: `tests/contracts/test_board_state.py` (13), `tests/hiru_ai/test_board_check.py` (4),
`agents/board_inspector/tests` (3). Changed: `tests/contracts/test_board.py` (tall parts of 6),
`tests/contracts/test_board_update.py` (the lab golden plus this plan's two documented differences).

Checks: ruff clean on every changed file; mypy clean; `hiru_ai validate` 201 parts, 0 errors; catalog current; every
board, frame, Zora-pin and contracts test passes. The full suite: 6300 passed, 68 failed, none in code this plan
touches (Raphael system/ledger/api scripted replies, script_split, Adam, Jonathan, parity, reader ingest, the three
`test_removal` lists; none of those modules import `contracts.board` or `frame_render`). They come from other
uncommitted work in the tree. Also not this plan's: the import linter's layers contract (`core.camera`,
`api.services.file_cache`, `media_thumbs`), E501 in four other files; interface: `raphael-panel.test.tsx` (length
caps).

## The person's

- **Live check (paid, ask first):** repaint the board of scene de75bc31 (Repaint whole board, LOW) and look at it: no
  umbrella (or it is reported in conflicts), clay props in a hand, two arms, feet on the pavement; then two first
  frames from it (the clay turned back into the real phone). About $0.15-0.18 a part (3 parts of 6 for 14 shots), a
  few cents of board checks, $0.13-0.19 a frame.
- F3: the staging map with an empty `basis` (a separate fix).

## Follow-up of 2026-11-23 (after the live board, version 11)

The person read the story: scenes 2 and 3 give Anudi a handbag and an open umbrella, so Q6 is REVERSED.

- Writer rules (`system.md`): "THE SHOT'S OWN OPENING IS THE TRUTH" (opening picture and subjects, then
  `opening_state`, then hands and marks: the marks ran ahead of shot 1's handover); "WHAT A PERSON CARRIES CONTINUES"
  (the scene condition and look carry things on, in the hand free of the plan's action; a conflict only when no hand
  is free); "PROPS ARE STAND-INS; THE PLACE IS REAL" (the food three-wheeler, a canon place, came out as a clay van).
- `prop_line(props, places)` names the places that stay real (`Board.place_names`); `writer_findings(..., carried)`
  allows what a person carries (`Board.carried`: condition + accessories); `_held` reads only "the clay X" (it read
  "edges" and "broad-plane-up" as things).
- Canon, written in the database at the person's request (with audit rows, `actor_agent: claude-code`): P04 "and"
  renamed "handbag" (its card was already Anudi's handbag), P16 "umbrella" added (navy folding umbrella). Neither has
  a reference sheet yet.
- The frame_render worker was restarted on the new code (`start-functions.ps1 -Only hiru-frame-render`).
- Parts 3 (carry across scenes) and 4 (the first frame follows the board) are plan/2026-11-23d.
