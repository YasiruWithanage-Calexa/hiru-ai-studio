# Shots planned by a director: what is built

Plan: [PLAN.md](PLAN.md). **Phases 1 to 7 are built and tested offline, and Phase 8's offline half is built**
(2026-11-01). What is NOT done is Phase 8's blind A/B with a person and every model-quality run (see "Phase 8").
Nothing is deployed, nothing was run against OpenAI or the hosted database, and no Episode 1 scene was re-split
(that is D5). The 6 API tests that fail in `tests/api` (`test_handoff` 2, `test_looks` 1, `test_production` 3) fail on
a media-link URL (`.env` has `API__PUBLIC_URL=http://localhost:8001`, the tests expect 8000); they are not touched by
this work.

Decisions D1 to D4 and D6 were taken at the plan's recommendations: holds and reactions of people already present
(D1), breath 15 to 30% of a scene with priority 1 never dropped by code (D3), report "needs X s, Y s without optional
breath" (D4), phases 1 to 3 first (D6). D2 (move bridges) belongs to Phase 4.

## Phase 1: the scene reading

- `contracts/reading.py` (new): `SceneReading` (`about`, `value` start/end, `tone`, `units` with `wants` and
  `turn_block`, `subtext`, `breath`, `ending`, `by`, `for_version`, `basis`). `validate` checks a model's (or a
  person's) answer entry by entry and **drops** what is wrong: a block that is not there, a person who is not in the
  scene (speaks, or is named in an action), overlapping or backwards units, two breaths on one block, a second
  button, seconds outside 1 to 3, priority outside 1 to 3, a breath with no `why`, a breath no turn, unit end or
  subtext entry earns (a button needs none). `complete_subtext` gives every STORY NOTE behaviour or a "narration
  only" entry with a reason. `by_rules` is the free reading (a turn is a line that follows a `with_line` reaction,
  or a ring/arrival; one priority-1 reaction per turn, a priority-1 button on the last filmed action, no verbs).
- Blocks are referenced by number **and by identity** (`block_key`: kind + words, a line's id). `basis` is a
  fingerprint of the blocks the reading was written for. A reading is stale when the script version moves or the
  basis differs; a stale reading still times the scene, because `resolve` finds a breath's block by identity after
  a script edit moved the numbers.
- `script_split/engine/reading.py` (new): one `high` call per scene (`scene_reading` schema, phase
  `script_split.reading`). The static system prompt carries the studio's craft rules (copied word for word from
  `knowledge_base/craft/directing.md` and `editing.md`; a test fails if they drift). The user message carries the
  episode synopsis, the scenes either side (heading and title), the director's note, the characters' summaries and
  the whole scene listing, STORY NOTEs included. No key, a failed call or an answer with no `about` and no units
  falls back to `by_rules`. A person's reading is never replaced (stale or not); one made for these blocks and this
  script version is not made again.
- `pipeline.run`: the reading is made after `prepare`, written with the shots in the same scene update
  (`scenes.reading`), and applied to the items before planning. `Store.neighbours` and the extra `episodes` /
  `characters` columns feed the context.
- API: `GET`, `PUT`, `DELETE /v1/productions/{id}/scenes/{id}/reading`. `PUT` needs the director permission, is
  refused on an approved scene, and returns how many body entries the checks dropped. It re-times the stored shot
  list with the new holds (lengths a person set stay; the others are sized again from what they hold). The scene
  view gains `reading`, `reading_stale`, `timeline.breath_s`, `timeline.core_need_s` and `holds` on each shot.
- Database: `scenes.reading jsonb` (migration `20261101112507_scene_reading.sql`), folded into the unreleased v9
  pair (`schema_v9.sql`, `upgrade_v8_to_v9.sql`) and noted in `Database/README.md`. **A project already on v9 must
  run the one `alter table`** (see the README), and until then the split's scene update fails on the unknown column.

## Phase 2: the kernel gives feeling time

- `contracts/timing.py`: `HOLD_RANGE_S` (1 to 3 s), `TURN_GAP_S` (1.0 s), `BREATH_BAND` (15 to 30%). Mirrored in the
  interface's `src/lib/veo/timing.ts`, with parity tests on both sides.
- `contracts/shotplan.py`: `Item` gains `hold_s`, `hold_kind`, `hold_priority`, `hold_who`, `turn`. `shot_clock`
  treats a hold as a pause after its block: the next picture or line starts after it, and when the shot ends there it
  **replaces `TAIL_S`**. The line that answers a turn line waits `TURN_GAP_S` instead of `LINE_GAP_S` (the longer of
  that and a hold). `FittedShot.holds` lists (block, seconds, kind); `FitResult.breath_s`, `unearned_silent_s`.
  `timeline_text` shows "[then hold 1.5 s, reaction]". A hold is time on an existing block, never a new block.
- `reading.apply(items, reading)` puts the time on the items; a `with_line` block that is a turn becomes `act`
  (1.5 s, not 0.5 s). `sceneplan.scene_items(scene, lines)` is now the one way every place reads a scene's items
  (API timeline and re-timing, production states, the director's working copy, frame render, shot producer), so they
  all agree with the split. `item_row` / `item_of` carry the hold through the director's edits.
- A scene with no reading times exactly as before (tests prove it: same arithmetic, same shots).

## Phase 3: the planner plans by turns; silence is budgeted

- `planner.PLAN_SYSTEM` (still static): the two "silent shots only for beats the script names" / "add no silent
  shots" rules are gone; new rules say to plan by the reading's units and turns, to show every turn's reaction (inside
  the shot or, for priority 1, as its own shot), to prefer breath inside a shot over a four-second cutaway, to end on
  the reading's ending image, and that breath comes only from the reading. The user message gains `<context>` and
  `<reading>` before the script, and the listing marks `[FEELING TURNS HERE]` and `[HOLD 1.5 s after it: ...]`.
- `critic.CRITIC_SYSTEM`: "Do not ask for a reaction or an insert the script does not name" is replaced by "Breath
  comes only from the reading"; it must not ask to shorten a hold and flags a turn whose reaction is not in frame.
- `planner.fold_breath` (with `fold_silent` kept as its second step): over the envelope it gives up optional breath,
  priority 3 then 2, later blocks first, keeping a drop only if it shortens the plan; priority 1 is never dropped by
  code. `fold_silent` no longer folds a shot that carries a hold. `rules_plan` returns the items that still carry
  holds and the shots; the model plan and the rules plan are then fitted and scored on the same items.
- The rules planner frames a speaker's shot as TWO when the hold at its end is a reaction by someone else (the
  listener is in frame while it plays).
- `critic.kernel_score(result, reading, items)` is now (issues, shots with two speakers, **priority-1 breath the plan
  does not play**, **seconds of breath outside the band**, seconds over the envelope, **silence nobody earned**).
  `SILENT_SHARE_MAX` applies to unearned silence only (a shot's seconds less the holds in it). A scene whose reading
  asks for no breath scores as before. The model critic still writes notes; code picks the plan.
- `fit_report.breath` = `{kept_s, dropped: [...], needs_s, core_need_s}`: for example "needs 61 s, 59 s without optional breath".
  The breath given up for the envelope is switched off on the reading (`off`, `off_by: "envelope"`), so the API times
  the stored scene the same way; a new split weighs the envelope again (`clear_envelope`), a person's own switch-off
  stays.

## Deviations from the plan, and what to know

- **The "plan that drops a priority-1 reaction loses" test is about fits, not framing.** Holds are added by the
  kernel to the block they follow, so a plan cannot lose one by shape; `breath_missing` catches a plan fitted without
  it. Whether the face that reacts is actually in frame (`turn_unseen`) is Phase 4 and 5 work; Phase 3 only frames the
  rules plan so that it is.
- `kernel_score` keeps `two_speakers` second (an existing test pins index 1) and puts the breath terms after it.
- `unearned_silent_s` removes only holds from a silent shot's seconds. Action time in a silent shot still counts as
  silence, as it did, so a scene with no reading scores exactly as before.
- Scene neighbours are heading and title only (not their scripts). Canon summaries come from the current card.
- Re-timing after a change to the reading (PUT, DELETE) sizes unlocked shots again from what they hold; it does not
  keep a length the planner once asked for.
- The rules reading gives a reaction to every `with_line` look before a line, including "Anudi laughs". It follows the
  plan's wording; tune it with the A/B (Phase 8). Scene 2 under the rules reads four breath moments (6.5 s, against an envelope of 35).
- The plan's D5 (re-split a copy of Episode 1) and every model quality question are untested: no OpenAI call was made.

## Phase 4: staging and the teleport check

- `contracts/stagemap.py` (new; the plan said "extend `staging.py`", but that module is about who is SEEN and imports
  the producer, so the map got its own module). `SceneStaging`: 2 to 6 `zones` (never `off`) and `marks`: from this
  block on, this person is in this zone, `facing` (left | right | camera | away), `frame_side` (left | right | centre),
  `holding`. **A mark holds until that person's next mark**, so the model says only what changes. `validate` drops what
  is wrong (block out of range, a person not in the scene, a zone not in the list, a direction outside the closed
  lists, a second mark for one person on one block); a map with fewer than two zones is no map. Blocks are referenced
  by number and by identity, like the reading (`basis`, `for_version`, `stale`).
- `script_split/engine/staging.py` (new): one `medium` call per scene (`scene_staging`, phase `script_split.staging`),
  given the script listing, the reading and the location's card (`Store.locations`, optional). No key, a failed call or
  an answer with no usable marks leaves the scene **without a map**, and then nothing about places is checked or
  written. A person's map and one made for these blocks and this version are not made again.
- Code finds the problems (`stagemap`): `teleports` (a zone change between two marks with no `move` block between
  them that names the person or names no one; entrances and exits through `off` are not teleports), `line_crossed` (two
  consecutive shots swap two people's sides of the frame, same spots, no `match` link) and `eyeline` (two singles on two
  speakers that face the same way). `unplaced` names people the map gives no mark.
- **The move bridge** (`bridges.py`): for each teleport, code (not the model) adds ONE implied action block, "Anudi
  crosses to the gate." (`screen: move`, 2.5 s, `by: staging`, `bridge: "move:anudi"`), before the block where the person
  is already somewhere else. The model's marks are what reveal the teleport; it never writes the step. Unlike the phone
  bridges, a staging step is **not** stripped by a re-split (a map made again does not duplicate it); a person removes it
  and it is remembered as `move:<who>` in `skip_bridges` **on the block that follows it**. `skip_bridges` now persists on
  action blocks too (`items_for`, `item_row`, `script_rows`, `bridges.carry`/`skip_bridge`, the director chat's
  `_remember_removal`), so a scene with no dialogue can remember a removal. `insert_moves` returns where every old block
  went; `reading.remap` and `stagemap.remap` carry the reading and the map across the new blocks (a person's reading that
  is already out of date keeps the numbers it had).
- Pipeline: `stage()` runs after the reading and before the plan; the map goes to `scenes.staging`, the report to
  `fit_report.staging` (`zones`, `teleports`, `line_crossed`, `eyeline`, `unplaced`, `moves`).
- API: `SceneView` gains `staging`, `staging_stale`, `staging_findings` (the checks against the stored shots); each
  `ShotView` gains `places` (where the people it shows are as it opens) and each hold its `priority` and `who`.
  `GET /scenes/{id}/staging`; `DELETE` (director) hands the map back. **There is no `PUT`**: a person cannot write a map
  yet (the interface only shows it and hands it back). Removing a move step uses the existing `DELETE .../script/{index}`.
- Database: `scenes.staging jsonb` (migration `20261101125025_scene_staging.sql`), folded into the unreleased v9 pair and
  `Database/README.md`. **A project already on v9 must run the one `alter table`**, or the split's scene update fails.

## Phase 5: three critics, one judge

- `critic.review` runs three reviewers in parallel, each with its own static prompt over the same data (script, reading,
  staging, `CODE FOUND` lines, the shot list): **coverage** (today's prompt, `high` tier), **emotion** (Murch's order:
  every turn's reaction seen, the feeling moves, the ending lands) and **editor/continuity** (motivated cuts, screen
  direction and eyelines, rhythm), both `medium`. Notes carry a severity (1 to 3); they are merged by severity, repeats
  said once, **at most six**, for the one bounded re-plan. A reviewer that fails is left out; all failing raises (the
  pipeline then keeps the first plan). The model critics never pick a plan.
- `kernel_score` is now ten terms, compared left to right: significant issues, shots with two speakers, priority-1
  breath not played, **`turn_unseen`**, **`teleport`**, **`line_crossed`+`eyeline`**, **`no_button`**, breath outside the
  band, seconds over the envelope, unearned silence. `turn_unseen`: a priority-1 reaction held after a LINE, by someone
  who is not its speaker, in a single of the speaker (a reaction after an action is that action's face; a heard voice is
  played on its listener; a TWO, OTS or WIDE shows the listener, unless the map puts them in another spot).
  `no_button`: the reading asks for a last image and the plan does not end on it.
- Tests that pinned one critic call now expect three `shot_review` calls (`test_split.py`).

## Phase 6: performance reaches the prompt

- `shot_producer/engine/feeling.py` (new): `feeling_for(reading, staging, scene items, shot items, beat windows)` cuts
  the reading and the map down to a shot: **behaviour to play per beat window** (story notes as behaviour, held
  moments as "Anudi's face receives it, held 1.5 s (why)"), **which beats are turns**, what each person **wants** in this
  part of the scene, and **where everyone is when the shot opens and closes**. A reading that is out of date still gives
  holds and turns (found by identity) but not unit numbers or story notes (found by number).
- Intent agent: the scene prompt carries the reading and the map; the system text says `purpose` and `emotional_beat`
  COME FROM the reading; the free rules take them from it too ("where the feeling turns (Anudi wanting to hide it)",
  "joy to dread").
- DoP: the shot block gains `PERFORMANCE`, `WHAT EACH PERSON WANTS`, `POSITIONS WHEN THE SHOT OPENS / CLOSES`; the
  static system text gains the rules for `beats[].performance` (one sentence of what the face and body do; never words,
  an inner thought or a mood adjective) and for positions. Clip schema: each beat gains `performance`, each subject
  `position`. `fit_beats` keeps `performance`; the rules design fills both from the feeling.
- `serialize`: the beat text carries the performance as a plain sentence; a line's delivery parenthesis carries what
  the speaker wants ("softly, wanting to hide it"). Prompt check "Performance written where the feeling turns".
- Continuity ledger: the end positions of the previous shot are carried ("S01 left everyone here: ..."), also into a
  joined shot's `carried` text.
- Free checks (`critique.free_problems`, which also steer the one DoP revision): **`performance_missing`** (a turn beat
  with no performance) and **`position_jump`** (the first frame names a spot of the map that is not where the people
  stood). `position_jump` is a substring match on the map's spot names, so it only fires when the frame names a
  different spot; it is advice, not a block.

## Phase 7: interface (`hiru-ai-studio-interface`)

- Types and mapper for the reading, map, findings, holds and places (`features/scenes/types.ts`, `lib/map-scene.ts`);
  pure helpers with tests in `lib/feeling.ts`.
- **Scene header**: "Needs 42 s · 37 s without optional breath · envelope 35 s" (plus a "Breath N s" chip) in the shot list.
- **Breath on the timelines**: hatched segments on the Director timeline (foot of each shot) and a "Held for feeling"
  lane on each shot's own timeline, with kind, who and priority.
- **The Scene tab** in the shot list panel (`SceneCard`): about, feeling start → end, tone, where it turns and what each
  person wants, the held moments with a **switch (played / off)** and a **priority select** per moment, story notes as
  behaviour, the last image, edit form, "Hand back to the system". Any edit saves the whole reading as the person's
  (`PUT .../reading`) and says how many entries the server dropped. A priority-1 moment's switch is disabled: lower its
  priority first.
- **Staging map** (`StagingMap`): the spots in a row with the people the picked shot opens on, "Not in the place" for
  `off`, warning chips for teleports, crossed lines and eyelines, "Hand the map back". Move steps appear in the script
  with the existing "Implied" chip and Remove button.

## Phase 8: eval

- `scripts/eval_staging.py` now runs the reading, the map and the new checks. New scenes: `silent_arrival` (an entrance
  that is no teleport) and `yard_unwritten` (a person who crosses a yard the script never writes; the step is added).
  A case may carry `"staging"`: the map a model would answer (marks name their block by a piece of its text), so the
  steps and checks run **offline**. Metrics: `turn_unseen`, `teleport`, `line_crossed` (ceilings 0, every mode),
  `button_present` (floor 1.0) and `breath_band` (floor 0.6) on rules, `inner_as_behaviour` (floor 0.8, model mode
  only: the free rules leave a note as narration, so it scores 0.0 there). Rules baseline: breath_band 0.667.
- **Not done**: the blind A/B with a person on 3 to 5 Episode 1 scenes (D5), any run with a key (so no model number is
  recorded and the `model` floors besides `inner_as_behaviour` and `button_present` are still empty), the latency
  measurement against `TIME_BUDGET_S`, and `npx supabase test db` / the dump comparison (no Docker).
- Calls added per scene on a split: staging (medium) + two more critics (medium, parallel with the coverage critic), plus
  the reading's one from Phase 1.

## Verified, and what is not

`ruff check src tests scripts`, `mypy`, `pytest` (1037 pass; the 6 URL-related API failures listed at the top are the
same ones), `scripts/eval_staging.py --rules`, and in the interface `npx next typegen && npm run check` (123 tests;
one pre-existing lint warning in `script-edit-form.tsx`). `npm run format:check` fails on 60 files in this working copy
before and after this work (CRLF checkout); the new files pass Prettier.

## Deviations and what to know

- The move step is written by code from the map's teleports, not "proposed by the staging agent" as the plan words it.
- `frame_side` and `facing` are one fixed geometry per person from a mark on; the 180 degree check compares the map at
  the first block of two consecutive shots, so a "crossed line" is whatever the model's marks say. It does not see two
  halves of one logical shot that the kernel split.
- `turn_unseen` reads a reaction after a line only; the planner's own rules already frame a TWO for it.
- The location card text is passed to the staging call as `<place>` when the store has `locations`; the fixture store
  and the tests have none.
