# plan/2026-11-18c: what is built

Phases 1 to 4 built offline on 2026-11-18, backend only, uncommitted. Paid lab calls, each with the person's yes:
$0.37 (two Raphael re-plans), then $0.38 (one re-plan + two LOW boards). Phases 5 to 11 are open ([PLAN.md](PLAN.md)).

## Built, file by file

**Action budget**
- `src/libs/contracts/action_budget.py` (new):
  - `count(beats) -> Count`: hard actions, moves and travel; `Count.over()` says why a clip is over, with the fix.
  - `door_left_open(clips)` and `turned_away(opening)`.
  - It is the lab counter (`lab/action_budget/count.py`) typed and tightened:
    - a door needs a verb ("with the door shut" is a state);
    - water and weather are no one's action for any hard verb;
    - "gives a small nod" is a move.
- `src/libs/contracts/raphael/checks.py`: `action_budget(work)`, called at the end of `check_stage1`. It gives blocking
  `action_budget` faults, keyed `action_budget:<clip>`, `door_open:<clip>` and `speaker_hidden:<clip>`. `check_stage2`
  runs stage 1's checks on the whole bin, so the cinematic clips keep the budget too.
- `src/libs/hiru_ai/house_rules/action_budget.md` (new): H-16 v1, `default`, topic `coverage` (Raphael planner and
  cinematic subscribe since plan/2026-11-18b). The text is the lab's H-91 with "nothing half done" and the speaker
  opening.

**Rain (section 4)**
- `src/libs/contracts/frame_brief.py`: the weather phrase no longer reads `look.light` (the sequence's colour script).
- `src/libs/contracts/board.py`:
  - the board prompt keeps people, props, light and grade the same in every panel; the weather and the ground follow
    each panel;
  - `NEIGHBOURS` (one panel repainted) does the same.
- `src/libs/hiru_ai/agents/board_writer/prompts/system.md`: the rule "WEATHER THAT CHANGES IS SAID IN EVERY PANEL";
  `world` carries the weather only when it does not change.

## Tests

- New: `tests/raphael/test_action_budget.py`, 9 tests:
  - the person's five cases in the planners' own words;
  - chains;
  - nouns, body parts and weather;
  - the hand routine;
  - states;
  - the door;
  - the speaker;
  - the faults Raphael gets.
- New: `tests/contracts/test_frame_brief.py::test_the_sequence_colour_script_never_brings_weather_into_a_dry_shot`.
- Changed on purpose:
  - `tests/raphael/test_implied_packet.py`: H-16 v1 after H-15 in both Raphael prompts.
  - `tests/contracts/test_board_update.py`: the panel-edit lab golden is compared with its NEIGHBOURS sentence swapped
    for today's (only that sentence changed).
  - `tests/raphael/fixtures/stage1_bin.json` and `final_bin.json`, gold clip c03 (1C-1). It was "C02 steps out,
    closes the door with her hip, then nears the stall; her phone slips and drops", three hard actions in one clip.
    It now reads "C02 stands near the stall, already out of the car with the door shut; her phone slips from her hand
    and drops near the awning edge". The gold bins are replayed by scripted models that cannot re-plan, so they must
    keep the budget.

**Raphael suite**: 222 passed, 5 failed.
- 4 were failing before this work: `test_api` x2, `test_isolation`, `test_removal`.
- `test_checks::test_the_bin_over_each_cap_fails_and_at_the_cap_passes[1]` also fails with the budget check switched
  off: an older failure.

ruff and mypy are clean on the changed files.

## Lab

`lab/action_budget/`: `export.py`, `count.py`, `replan.py`, `board.py`, `h91_action_budget.md`, `runs/`, `README.md`.

## Phases 6 to 8 (built offline 2026-11-18, second session, $0)

**Phase 6, Sable and Zora** (`contracts/coverage/checks.py`)
- `budget(cov)`, called from `find`, gives the three H-16 faults on the clips as edited: `action_budget:<h>`,
  `door_open:<h>` and `speaker_hidden:<h>`.
- `new(before, after)` keeps only what an edit introduced, so each caller hears only its own faults:
  - Zora's author is asked to repair them (`fix: repair`);
  - Sable's `sable_shot_change` / `sable_shot_try` say them back to Sable (`row_trial.problems`);
  - a person's own click or Accept (Zora `actions`, Sable `actions`) only reports them.
- `contracts/action_budget.py` gains `beats_of(ir)` and `opening_of(ir)`, which read a stored clip.
- Tests: `tests/zora/test_rows_coverage.py` (+4).
- The fixture scene was planned before H-16, and its key handover clips (S14, S15: lift the key and place it in Dinu's
  palm) are real over-budget clips. The tests now name them (`PRE_BUDGET`) instead of expecting a clean scene.

**Phase 7, the chip and the prompt check**
- Backend:
  - `contracts/handoff.ShotNow.actions` and a `check_prompt` line: "Actions within budget" (pass) or "Over the action
    budget: <why>" (advisory, never blocking). `api/routers/handoff.handoff_checks` feeds it the IR beats (else the
    shot's beats).
  - `build_plan` already carries non-pass handoff checks, so the Video card shows the advisory too.
  - `ShotView.over_budget` (`api/routers/scenes.py`): why, or "".
- Interface:
  - `Shot.overBudget` (`features/scenes/types.ts`, `lib/map-scene.ts`);
  - an amber "Too much action" chip beside "Crowded" in the Director shot list, with the reason as its title.
- Tests: `tests/contracts/test_handoff_budget.py` and `map-scene.test.ts` (+1).

**Phase 8, take reject reasons**
- Backend:
  - `contracts/handoff.REJECT_REASONS` (wrong_action, too_many_actions, object_vanished, camera_moved) and
    `reject_reason(codes, words)`;
  - `RejectTake.codes` (a Literal list; an unknown code is 422);
  - the take's `reason` reads "Too many actions; Camera moved · lips drift";
  - the codes are kept in the `take.reject` audit row. No schema change: the takes table has only the text column.
- Interface:
  - `REJECT_REASONS` / `RejectCode` (`features/handoff/types.ts`), `rejectTake(..., codes)`;
  - the reject form in `takes-log.tsx` shows the four reasons as toggles (shadcn ToggleGroup) above the free text.
- Tests: `tests/contracts/test_handoff_budget.py`, `tests/api/test_handoff.py` (+1), `takes-log.test.tsx` (new).

**Phase 9 not built**: the plan ties it to takes that show a difference between the models. Phase 8 now collects the
reasons that will show it. `Count.over(hard_max, all_max)` already takes the numbers.
- The test files moved to `tests/raphael/` (`test_accident_coverage.py`, `test_action_budget.py`): `test_isolation` allows no Raphael import outside the Raphael folders.
