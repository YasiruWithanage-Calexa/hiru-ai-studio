# Shots measured in pictures: what is built

Plan: [PLAN.md](PLAN.md). Phases 1 to 8 are built and tested offline, and the offline part of Phase 9
(the eval) is done (2026-11-01). Nothing is deployed, nothing was run against OpenAI or the hosted
database, and Scene 2 itself was not re-split (that is D4, below).

Decisions D1 to D3 were taken at the plan's recommendations: implied steps from a closed rules list
(D1), report and let the director choose, never squeeze (D2), move 2.5 s / act 1.5 s / under a line
0.5 s (D3).

## Phase 1: the kernel keeps a picture clock

- `contracts/timing.py`: `SCREEN_SECONDS`, `action_seconds(screen, events)` (unknown kind counts as
  `act`; each extra event adds its own time). Mirrored in the interface's `timing.ts` with the same
  cases.
- `contracts/shotplan.py`: `Item` gains `screen`, `events`, `implied`, `by`, `for_version`, `skip`,
  `bridge`. `shot_clock(items)` puts a shot's blocks on one clock: an action adds its seconds, a line
  starts after the pictures before it (never before the 0.5 s lead-in), `TAIL_S` only when the shot
  ends on a line. A shot of lines alone times exactly as before. Line `start_s` and `beat_index` come
  from this clock, so a voice after "phone rings" lands after it.
- `split_to_fit` (was `_split_long`): an unlocked shot that needs more than the longest rung is cut at
  a block boundary, never inside a line; a small action that plays under the next line stays with it.
  A follow-on that starts on a line is `continuous`, one that starts on an action is a `cut`.
- Issues: `crowded` (a locked or fixed-length shot holds more than its length; "S05 needs about 10.9 s
  to show what it holds; it is 8 s.") and `split` (the proposal held more than one shot can show and
  the kernel had to cut it; this is what makes a model plan lose to the rules plan). `FittedShot`
  gains `picture_s`, `need_s`; `FitResult` gains `need_s`, `crowded`.
- `sceneplan.fit_report` stores `crowded` and `need_s`. `sceneplan.items_for` reads an action block
  nobody has read yet by the free rules, so the clock always runs, with or without a key.

Deviation from the plan: a silent shot (no lines) is still at least as long as the old word-count
rung says, so existing silent shots do not get shorter; `need_s` for it is the picture clock.

## Phase 2: reading the script as pictures

- `contracts/beats.py` (new, pure): the rules reading (`move / act / with_line / info / inner` and the
  number of events), sentence splitting that does not break "Rs. 5,000", `annotate` and `is_stale`. A
  block is read sentence by sentence: a thought or a piece of information only makes the whole block
  "inner"/"info" when nothing filmed is in it.
- `script_split/engine/beats.py`: one `medium` call per scene (`beat_screen` schema), validated block
  by block; the rules fill what the model left out or got wrong. Stored on the script blocks with the
  `script_version` and `by`. A scene is read again only when its script version moves. A person's marks
  (`by: person`) are never replaced.
- `structure_build/engine/prose.py`: the prompt asks for one visible event per action block and for
  `seconds` that count what is seen; `by_rules` splits an action paragraph at its sentence ends.
- The intent and DoP prompts show `inner` as "STORY NOTE (not filmed)" and `info` as "THE VIEWER
  LEARNS: ... (show it with an insert, a line or a look)".

## Phase 3: implied steps

- `contracts/bridges.py` (new): `answer_phone` and `lower_phone`, rules only, never a line, a person or
  a story event. The holder comes from the script and the production's cast (a person who never speaks
  in the scene still holds the phone). A script that already says "she answered" gets none.
- A removed bridge is remembered on the phone line's script block (`skip_bridges`), so a re-split never
  brings it back. No database change: it lives in `scenes.script` (JSON).
- `script_split.pipeline.prepare` adds the steps and reads the blocks before planning. The API's script
  edit carries readings and implied marks across (`bridges.carry`) and remembers a dropped step.
  New: `DELETE /scenes/{id}/script/{index}` removes one implied step.

## Phase 4: the planner and the critic see time

- `scene_listing` shows each block's kind and seconds (`ACTION (act, 1.5 s)`, `INFO (needs a carrier)`,
  `STORY NOTE (not filmed)`). `PLAN_SYSTEM` (static) gains the picture-time, turn-in-feeling, INFO,
  heard-voice and move rules.
- The rules planner now cuts a group that is too full where the kernel would, so each part gets its own
  size and sound (a ring is a medium shot, the voice is an MCU on the person who holds the phone).
- `critic.describe`: `need X s in Y s` per shot and `CROWDED:` replaces `BUSY:`. `crowded` and `split`
  are significant, so a crowded plan always loses to an uncrowded one.
- `fold_silent` stops when a fold would crowd the shot that takes the action in; the scene then reports
  its need (Phase 6) instead of hiding it.

## Phase 5: the same checks wherever a plan changes

- The director's `persist` and the API re-timing both store `crowded` and `need_s` through
  `fit_report`. The director kernel keeps `notes`: a merge that cannot fit one shot says "S05 would need
  10.9 s ...; the longest shot is 8 s, so it becomes 2 shots", in the continuity note and in an
  option's impact line. A rewritten action block is read again (rules now, model at the next split);
  removing an implied step in chat is remembered.
- Approving a scene with crowded shots asks once in the interface; it never blocks.
- A plain message "Split S05 at block 12." now names the block exactly (the interface's "Split here").

## Phase 6: honest envelopes

- The envelope issue says what the script needs ("The scene needs 42 s on screen; its envelope is 35 s
  (7 s over)."); the build log says "Episode 1: needs 78 s to show its script; target 60 s".
  Nothing is merged or dropped to hit the target.

## Phase 7: intent and DoP work on the timeline

- Both prompts carry the TIMELINE (`shotplan.timeline_text`) and numbered blocks. The intent schema
  gains `split_after` (the last block of the first part) and `split_reason`, validated against the
  shot's blocks and stored on the intent.
- Free checks in `contracts.staging`: `skips_beat` (a filmed block whose key words are missing from
  what we see) and `size_vs_intent` (an MCU or CU whose intent says two-shot, wide, walks away).
- `fit_beats` maps the DoP's beats to the kernel's windows by time. A heard line's beat in the video
  prompt says what happens first ("Anudi answers the phone; then the voice: ...").
- `cast_in` and the heard-by-rule check ignore people named only in information or thought blocks
  ("It is Dilini, his sister."), so a caller is no longer pulled into the ring shot's frame. The rules
  intent leaves out what is not filmed and frames a voice on the person the last actions are about.

## Phase 8: interface (`hiru-ai-studio-interface`)

- `timing.ts`: `SCREEN_SECONDS`, `actionSeconds` with parity tests.
- `ShotTimeline` (new): the shot on its own clock, pictures, lines, beat windows, red past the cut.
  Used in the Production panel's "What this shot is for" and in the Director panel's shot details.
- "What this shot is for": `Crowded · needs 10.9 s in 8 s` chip, "Implied" chips with Remove, story
  notes greyed, "The viewer learns", and a "Split here" banner when the intent suggests one (sent as the
  director chat's own split). Both controls wait for an unapproved scene.
- Director panel: Implied chip and Remove in the script column, "Crowded" on shot cards, "Needs 42 s ·
  envelope 35 s" in the shot list header, one question before approving a scene with crowded shots.
- `map-scene.ts` / `types.ts` carry the new fields and still read an older API.

## Phase 9: eval

- `tests/eval/staging_scenes.json`: five new hard scenes (a call that breaks a moment, drop-pickup-run,
  an exit watched, a caller named only in prose, a closing thought). `scripts/eval_staging.py` now runs
  the real split step (`prepare`) first and splits action paragraphs into sentences like a new build.
- New metrics: ceilings `crowded_shots = 0`, `voice_before_source = 0`, `inner_filmed = 0` (counts, in
  every mode, `ceilings` in `staging_thresholds.json`) and the floor `info_carried >= 0.8`.
- Rules mode: heard_kept_out 0.846 (was 0.818 over fewer scenes), seen_shown 1.0, speaker_framed 1.0,
  size_variety 1.0, info_carried 1.0, crowded_shots 0, voice_before_source 0, inner_filmed 0.

## Existing tests that changed, and why

Actions are no longer free in a shot with a line, so a few expectations moved on purpose: the first
line of a shot with an action starts after that action (`test_shotplan`), the opening scene's third
shot needs 6 s (`test_split`), a whole scene is no longer one 8 s shot unless a person locked it (the
two Harbour Lights fixtures lock it), the "each episode fits its minute" test became "an episode that
needs more says so and nothing is squeezed", and `test_folding_stops_when_only_speech_is_left` totals
12 s (each action rides with its line).

## Checks run

Backend: `ruff` clean, `mypy` clean (root and each service), `pytest` 800 passed, 6 failed. The 6
failures are in `tests/api/test_handoff.py`, `test_looks.py` and `test_production.py` and were failing
before this work: the local `.env` sets `API__PUBLIC_URL=http://localhost:8001` and the tests expect
`:8000`. `scripts/eval_staging.py --rules` and `scripts/replay_director.py` pass. Interface:
`next typegen`, `npm run lint`, `tsc`, `vitest` (87 tests) pass; the touched files pass Prettier with
`--end-of-line auto` (the Windows checkout has CRLF files, which `format:check` reports for untouched
files too).

## Not done (needs the user)

- D4 / Phase 9 step 3: un-approve Scene 2, re-split it (unlinks the frames of the old S05 and S06),
  design it, make new frames. Expected: about 8 shots, about 42 s, a WIDE for the drop and run, the
  call over two shots, the exit in a WIDE. This touches the hosted database and paid frames, so it is
  waiting for the user.
- Run `python scripts/eval_staging.py` with a key, then `--update-thresholds` to record the model floor.
  The first-guess picture times (D3) are tuned on that run.
- The interface was not driven in a browser: it needs the API and a signed-in session.

## Review (2026-11-01)

Phases 1 to 8 and the offline part of 9 were checked against the plan; all are in place and
tested. Two fixes:

- **An overrun that was not reported.** `crowded` fired only for locked or fixed-length shots, so an
  unlocked shot of one block that shows more than the longest shot (e.g. four sentences of running,
  10 s) came out as 8 s with no issue. `fit` now reports `crowded` for any shot whose need exceeds
  its length, unless a line issue (`line_overrun` / `long_line`) in that shot already says so.
  Tests in `tests/contracts/test_shotplan.py`.
- **"Split here" was read by a model.** With a key, the interface's `Split S05 at block 12.` went
  through the conductor model. `conductor.is_exact_command` now sends that exact command to the
  rules reading, so the cut lands on the block the intent agent named. Test in
  `tests/services/director_chat/test_pictures.py`.

Checks after the fixes: `pytest` 808 passed with `API__PUBLIC_URL=http://localhost:8000` (the 6
known failures are only the local `.env` URL), `ruff`, `mypy`, `eval_staging.py --rules`,
`replay_director.py`; interface `next typegen`, `npm run check` (87 tests), Prettier on the changed
files.
