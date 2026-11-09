# Scene state ledger: what is built (plan/2026-11-09)

Status (2026-11-09): **phases 0 to 8 built offline, uncommitted, in both repos.** No model was called. Phase 9 (the lab,
~$0.60) and decisions D1 to D6 are the person's. The recommendations were taken as the working defaults: D1 extend the
stager, D2 report only, D3 no implied walks for Raphael, D4 Raphael first, D5 read-only map, D6 stager tier unchanged.

## What was built, phase by phase

| Phase | Where | What |
|---|---|---|
| 0 | `tests/raphael/fixtures/staging.json`, `staging_body.json`, `tests/raphael/test_state_baseline.py` | The roadside (b0-b22) and the body scene (plan/2026-11-08f scene 1, from the reader's gold transcription) read by hand into the stager's answer shape. The baseline pins five faults on run 3's bin (below). |
| 1 | `contracts/stagemap.py`, `contracts/holding.py` | `Mark` gains `posture` (closed list `POSTURES`), `left_hand`, `right_hand`, `condition`, `wearing`; `PropMark` and `SceneStaging.props` (`MAX_PROPS = 30`). `validate` drops a junk posture to `""`, adds a named hand's thing to `holding`, drops a prop mark on a missing block, and `settle` keeps hands and props from disagreeing. Pure state: `state_at`, `state_before`, `delta_text`, `clip_state`, `ledger_of`, `pinned`. `holding.Ledger` records the hand a mark names (`side`) and the Hands sentence says it ("in the left hand"); a mark without a side reads exactly as before. |
| 2 | `agents/stager` (schema, prompt, evals), `script_split/engine/staging.py` | The stager writes the new fields (all required, `""` allowed); six prompt lines; two new eval cases (roadside handover, body). The legacy engine's prompt and JSON schema are kept byte-identical; the three script_split parity fixtures were re-recorded (only the stager's system hash moved). |
| 3 | `systems/raphael/raphael_shot_planner` | `plan_one` keeps a person's or a current map (no call) or makes one with ONE stager call (`scene_prep.staging_for`, reached by id; no implied walks). A failed stager plans without a map and the job says "No state map for this scene; planned without it". A made map is saved with the shots (`replace_shots` fields; `save_plan` with no shots when the result is unchanged). The map is pinned onto the scene (`SceneS.staging`), so the input hash moves with it; a scene with no map hashes as before (`scene_dump`). |
| 4 | `contracts/raphael/scene.py`, `state.py`, both prompts | `BlockS.now`, `SceneS.opening_state`, `SceneS.codes`; the listing prints `At the start: …` under `Present:` and `| now: …` after a block whose state changes, capped at `STATE_LISTING_CHARS = 2400` (props in no hand go first). One `- STATE (plan/2026-11-09).` line in "The design of a clip" of both prompts; `test_lab_parity.py` allows exactly it. Gold scene: +553 characters. |
| 5 | `contracts/raphael/state.py`, `tools.py` | `clip_states`, `opens_ends`, `clip_blocks` (a blockless stage 2 clip plays its anchors' blocks); `read_bin` shows `opens:` / `ends:` only when one moment is asked for. |
| 6 | `contracts/raphael/checks.py` `state()` | Report-only faults (code `state`, owner `raphael`) in `check_stage1` (so also stage 2): `state:hand`, `state:handover`, `state:posture`, `state:condition`, `state:off`, `state:zone`, `state:unplaced`. No map, no check. |
| 7 | `contracts/staging.py`, `steps/raphael/raphael_write`, `steps/serialize`, `steps/frame_compose` | `ShotIntent.story`, `opens`, `ends` (the stamp includes them only when set, so no stored design goes stale). The write step fills story (the moment's `what`, plus "part k of n" over a long action), `emotional_beat` (the moment's feeling, was `""`), opens and ends. For `planner == "raphael"` only: the Subjects section adds the position and "As the clip opens: …" / "By the end of the clip: …", a new Story section ("What happens in this clip: …"); rules in the clip schema YAML. The first frame gets "In this frame, as the clip opens: …". |
| 8 | Raphael agents' manifests, `api/routers/scenes.py`, interface | `production_memory` with `memory: [camera, visual, lighting, performance]` (it fits the loop shape: the block goes once at the end of the first user message). `GET …/raphael` gives `states` (by slate: story, opens, ends) and `state_faults`; the stored `Left` row now carries the check's `key`. Interface: Opens / Ends lines and amber state chips on each clip card; the shared `StagingMap` (moved to `features/scenes/components/`, not copied) read-only on the Raphael tab, drawn by the server. |

## The baseline (phase 0), against the gold ledger

| Key | Clip | What |
|---|---|---|
| `state:handover:c05:phone:9` | c05 | "receives the phone": neither Kasun's giving hand nor Anudi's left hand |
| `state:zone:c07:Kasun` | c07 | "by the counter" after he ran after Anudi onto the pavement |
| `state:zone:c12:Kasun`, `state:zone:c14:Kasun` | c12, c14 | the closing clips put him back at the stall too (not in the plan's expected list; the same reading) |
| `state:unplaced:handbag` | — | in Anudi's description, never placed |

The cinematic pass (pass 5) adds no state fault of its own. Nothing blocks `finish`.

## Deviations from the plan

- `delta_text` says a prop in a hand once, on its holder ("Anudi: phone in left hand"), not again as a prop row; a prop
  row appears only for a prop in no hand ("phone: on the ground by the three-wheeler"). It keeps the listing short.
- `condition` and `posture` hold until a mark changes them (an empty field keeps the last), and `well` ends a condition.
  The prompt says so.
- `holding.Ledger.of` now merges a same-block "let go" + "take from nobody" into one handover (the order of two marks at
  one block decided it before). Every planner's ledger is better for it; the existing holding, frame and Jonathan tests
  are green.
- The listing cap lives in `state.attach` (the listing only prints the fields).

## Checks run

- Backend: `ruff check src tests scripts` (one long line left in `tests/api/test_production.py`, not this plan's),
  `mypy` (1010 files, clean), `hiru_ai validate` (183 parts, 0 errors), `hiru_ai catalog --check` (current),
  `scripts/lint_imports.py` (two contracts broken before this plan: `api.services.media_thumbs -> hiru_ai.core.thumbs`
  and David's agents importing `david.wire_schema`), full pytest: 5186 passed; every remaining failure also fails on
  clean `main` (compared case by case). The full run first showed 8 shot_producer parity failures from this plan
  (empty `story`/`opens`/`ends` keys in every planner's stored intent); `ShotIntent` now leaves them out when empty, and
  those 8 pass. `director_chat/craft_board-graph` failed once in a mixed run and passes alone and in the parity run
  (order-dependent, not this plan's).
- Already failing on `main` (18 of the full run's failures, beyond the parity cases below): api tests for handoff,
  looks, production frames and thumbs, the reader ingest test, the removal tests of Adam, David, Jonathan, Raphael and
  Zora (they name `Database/schema_v20.sql`). Three more fail only under `-p no:logging` (they use `caplog`).
- Interface: `npx next typegen && npm run check` (lint 0 errors, typecheck clean, 405 tests) and `npm run format:check`
  (20 files fail, all outside this change and failing on `main` too).
- Already failing before this plan, untouched: 5 parity cases (`canon_extract/model_cards`, `doc_ingest/embedding_down`,
  `doc_ingest/script_with_key`, `structure_build/prose_model`, `structure_build/prose_model_rejected`, graph engine) and
  `tests/raphael/test_removal.py` + `tests/adam/test_removal.py` (they name `Database/schema_v20.sql`).

## Left for the person

- D1 to D6 (above).
- Phase 9, the lab: the stager on Episode 1 scenes 1-3 and Raphael stage 1 + 2 with the ledger (~$0.60). It decides D2
  (whether a state fault blocks `finish`) and D6 (the stager's tier). No model call without a yes.
- Whether to bring the ledger into the Veo prompt for Adam, David and Jonathan (D4).
- A browser look at the Raphael tab's Opens / Ends lines, chips and map.
- Editing the map before planning (`PUT /staging`, D5): a later plan.
