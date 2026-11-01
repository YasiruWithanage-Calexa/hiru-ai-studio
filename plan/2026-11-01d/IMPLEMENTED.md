# Shots planned by a director: what is built

Plan: [PLAN.md](PLAN.md). **Phases 1 to 3 are built and tested offline** (2026-11-01). Phases 4 to 8 are not started.
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

## Not started

Phase 4 (staging map, `teleport`, `line_crossed`, `eyeline`, move bridges), Phase 5 (three critics, code judge),
Phase 6 (`performance` per beat, positions, `performance_missing`), Phase 7 (interface: the scene card, breath on the
timeline, staging map, header) and Phase 8 (eval scenes and the blind A/B). Phase 7 can already read `reading`,
`reading_stale`, `holds`, `timeline.breath_s` and `timeline.core_need_s` from the API.
