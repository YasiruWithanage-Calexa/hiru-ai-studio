# Scene board: what is built (plan/2026-11-14)

Built offline 2026-11-14, $0 spent, nothing committed, nothing applied to the hosted database. Phases 1 to 6 are built
in both repos. **Phase 0 and phase 7 (paid) are not run**: each needs the person's yes. Read `docs/scene_board/README.md`
for how it works.

## Phase 0 (paid, NOT RUN)

Waiting for the person's yes (~$0.25): (a) prove that `gpt-image-2` honours a mask on a board (repaint panel 1 of the
lab's run_014 board at LOW, check the other 8 panels are unchanged); (b) one MEDIUM frame of scene 01 shot 2 with props per
shot. **D7 (method A, masked repaint) is built but unproven** until (a) runs. If the mask is not honoured, the person
chooses (method B, a whole repaint with unchanged panels pasted back, is not built; the paste code exists for locks).

## Phase 1: contracts

- `contracts/board.py`: grid and parts (D5: 16 on one image, else parts of 12 with one overlap panel), the writer's input
  (`board_shots`, `shot_plan`, `writer_bundle`, `writer_message` + mannequin note, repaint notes), `Writer` (its answer,
  `merged` for a repaint), `board_prompt` / `repaint_prompt` (mannequin line, `BODIES`, no text, face sentences dropped),
  pins (`plan_pin`, `new_cell`, `stale_cells` → changed / added / removed / reordered), and the frame side
  (`mannequin_paragraph`, `state_line`, `unmannequin`, `frame_world`, `panel_text`, `frame_sections`).
- Pictures (Pillow, kept out of `contracts`): `hiru_ai/systems/frame_render/pictures.py`: `cell_boxes` (gutter-aware),
  `crop`, `paste`, `repaint_mask`, `scene_sheet` (code-drawn "SHOT N", black cells), `portrait_crop`.
- `contracts/canon.py`: `face_sheet_prompt` (the lab's gender-neutral prompt), `sheet_assets`,
  `face_sheet_path`, `keep_assets` (5 sheets + 2 face sheets kept, so neither pushes the other out); `CanonEntity` gains
  `face_sheet_url/thumb_url/key`.
- `contracts/frame_brief.py`: `sheet_path` never returns a face sheet; `plan_references` puts the face sheet of each SEEN
  person first (on top of the limit; someone only heard never gets one); `reference_job` / `references_block`: the face
  sheet owns the face, the look sheet only dresses; hair (D6) from the look when it sets hair; a never-cut "Scene board"
  section (`board=`).
- Tests: `tests/contracts/test_board.py` (11).

## Phase 2: face sheets

`hiru_ai/systems/frame_render/faces.py`: `render_face` (portrait crop → MEDIUM → `kind: "face"` asset) and `ensure_faces`
(D4). Route `state.reference_kind = "face"`; API `POST .../canon/{id}/face-sheet`. Today's frame path attaches face sheets
first through `plan_references` (both engines). **Not built**: the vision check of a face sheet (six views of one person);
the frame's existing checks cover the frames.

## Phase 3: the board

- Schema v25: `Database/upgrade_v24_to_v25.sql`, `schema_v25.sql`, `supabase/migrations/20261114120000_scene_boards.sql`
  (table, unique (scene, version, part), one approved per (scene, part), RLS read like `first_frames`, realtime;
  `first_frames.board_id` + check `draft_id is null or board_id is null`). **Not applied.**
- Agent `board_writer` (tier `board`: `OPENAI__MODEL_BOARD` default gpt-6.1-sol, `OPENAI__EFFORT_BOARD` default high; the
  lab's `prompt/system.md` moved unchanged; recorded-answer test from run_014's shape).
- `hiru_ai/systems/frame_render/board.py`: claim → face sheets → writer → per part: prompt → `blocking()` → LOW image →
  cells → sheet → store. Repaint in place by mask. The `ImageGen` port gains `quality=` and `mask=`.
- API `routers/boards.py` + `services/boards.py`; repository `scene_boards`.

## Phase 4: first frame from the board

`first_frames.board_id`; the graph attaches the panel LAST as the approved draft and adds the board sections; D4 face
sheets made once per job before the parallel frames; the frame inspector gains `mannequin` and `state_match` (advisory
chips). API: D3 gate on `POST .../shots/{id}/frames` and `.../scenes/{id}/frames` (only shots whose panel is approved and
current; black plates need none); drafts and `from_draft` refused for new frames; `ShotProductionView.frame_board`.
Props per shot were already limited by `contracts.holding.references_for` (the lab's loose phone/key came from the lab
attaching every prop).

## Phase 5: interface (hiru-ai-studio-interface)

Scene board card on the shot's Production screen (`scene-board-card.tsx`, `queries.ts` `useSceneBoard`, query key
`sceneBoard`, the shared status poll while painting, `<Media>` with `thumbSrc`, writes put the answer in the cache):
paint (Low / Medium), numbered panels and black cells, conflicts, approve, out-of-date banner with "Repaint changed
panels" and "Repaint whole board", a panel dialog with note, lock, repaint this panel. First-frame panel: paints from
the board panel, shows it, says why not and links to the board; draft section removed. Shot workspace: drafts tab
read-only ("Earlier drafts"), the "drafts" bulk action removed, frames wait for the board. Canon page: face sheet beside
the reference sheet with "Make face sheet". No costs anywhere.

## Phase 6: docs

`docs/scene_board/README.md`; `CLAUDE.md` section; `Database/README.md`; `.env.example`; frame_render `UPSTREAM.md`
divergence 10; lab README points at the product.

## Deviations (for the person to check)

1. **Engine**: the board, face sheets and frames from a panel are built in the `hiru_ai` graph only; the frame_render
   handler routes those jobs to it whatever `AI_ENGINE` says (the canon_extract refine precedent), rather than a second
   copy in the legacy pipeline.
2. **Versions**: a whole paint is a new version; "repaint changed panels" changes that part in place (new files, approval
   cleared, the old picture kept in force if the repaint fails). The current board is the newest version.
3. **Whole repaint and locks**: a locked panel's old picture is pasted back into the new board (the plan says a locked
   panel is never repainted; method B is otherwise not built).
4. **Overlap panel**: a later part gets the previous part's last panel as a reference picture to repeat.
5. **Old drafts** stay readable and acceptable; nothing new is painted as a draft.
6. **Not built**: the face sheet's own vision check; a sweeper for a board stuck `running` (the job's own failure path
   marks it failed).

## Checks (2026-11-14)

Backend: ruff (only pre-existing lines), mypy clean, `lint_imports` (only the pre-existing `media_thumbs` contract),
`validate` 194 parts 0 errors, `catalog --check` after `hiru-ai catalog`. pytest: baseline on a clean checkout of HEAD has
28 failures; the full run after this work found 6 new ones, all fixed (a second board_writer eval case, the legacy
inspector's schema, the tier list, the wiring snapshot, Pillow moved out of `contracts` into
`systems/frame_render/pictures.py`; one director_chat parity case was order-dependent and passes); the affected suites
then show only baseline failures. Interface: typegen, eslint (one pre-existing warning), tsc,
vitest 459/460 (the one failure, `raphael-panel.test.tsx`, fails on HEAD too), prettier clean on every changed file.

## Waits for the person

- **Apply schema v25.** Until then the API refuses new first frames of painted shots ("Paint and approve the scene board
  first"), because there is no board table (D3).
- Phase 0 (paid, ~$0.25): mask proof and the per-shot-props frame.
- Phase 7 (paid, ~$1.20, after v25): face sheets for Aruni, Nimal, Dinu; boards for scenes 01 and 02; four frames.
- Restart the frame_render function after pulling (no reloader).
