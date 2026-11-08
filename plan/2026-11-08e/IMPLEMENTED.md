# Raphael: what is built (plan/2026-11-08e)

## Phase 0a: the lab, free half (built 2026-11-08, uncommitted)

`lab/raphael/` (see its [README](../../lab/raphael/README.md)): the loop, `put_clips` (DaVinci's clip plan + `IrW` in one),
the one prompt, a scripted rehearsal on Episode 1 (edit plan, three sequences, a refused `finish`, one batch repair of two
clips, `finish` accepted in 7 turns), `dry`, the page, `pick`, 27 offline tests. DaVinci's checks, bin, money and backend are
imported (R2), so DaVinci's 44 tests still pass and nothing in `lab/davinci` changed. $0 spent.

Choices the plan left open, made in the lab (the person can change any):

- Every write's report ends with `Turns left after this one: N` (the fix DaVinci's notes asked for; no money is ever shown).
- STILL FAILING marks a fault only when the last write replaced one of its clips and it survived.
- D1: a run that stops early is saved, marked INCOMPLETE (recommended answer, not yet the person's).
- `paid` refuses a fourth run until the person's read.

## Phase 0b: paid runs

Three runs with the person's yes, $1.18 of the $5 lab budget, **all three reached `finish`** (4-7 turns). Details and the
questions for the person's read: [RESULTS.md](RESULTS.md). Two lab changes between runs, one per run:

- run 2: reports that are Raphael's (not `code`) are listed as his to fix, and the prompt says why (§3.2's two owners).
- run 3: an overrun's advice names the clip's blocks and says to split them across consecutive clips (`Raphael.advice`;
  DaVinci's check is unchanged).

`paid` now refuses a fourth run until the person's read (`--past-read`). 29 offline tests.

## Phase 0c: the stage 2 lab, free half (built 2026-11-08, uncommitted, $0)

In `lab/raphael/` (stage 1's files and DaVinci's lab otherwise unchanged; DaVinci's 74 tests still pass):

- `stage2.py`: `load_stage1` (a finished run's edit plan and bin; refuses an unfinished run), `CinematicPass` (stage 1's loop,
  a fresh conversation, slot `cinematic`, 12 turns), tools `put_extras` / `remove_extras` / `read_bin` / `finish(blend_notes)`,
  `extra_checks` (§3.5's table), `dump` (every clip carries `stage`; stage 2 clips `anchor` and `blend`).
- `schema.py`: `ExtraW` (a whole clip, `priority` only should / nice in the schema itself, `anchor`, `blend`), `Extra`.
- `prompts/cinematic.md`: the second prompt. `prompts/raphael_must.md`: S1's stage 1 prompt (must only), written, not paid
  for; `--prompt raphael_must` picks it; the default stays `raphael` so runs 1-3 stay reproducible.
- `rehearsal2.py`: the plan's script on run 3's real bin: an extra on a must id refused, a same-angle extra and three on one
  moment refused (with a refused `finish`), one `put_extras` that cures both, `finish` accepted. 5 turns, 4 cinematic
  clips, 86 s of 90 s, no must clip changed.
- `render.build_layers`: the page with a "cinematic layer" table, blend notes, a line proving the must clips are untouched,
  and each cinematic card marked *cinematic, optional* with its blend and anchor, under its moment.
- `run.py`: `stage2 dry | rehearse | paid [--from DIR]` (default run 3), `full` (stage 1 must-only + stage 2, one meter so
  the $5 cap covers both), `pick` adds one cinematic clip and its anchor. 25 new offline tests (54 in all).

Choices the plan left open, made in the lab (the person can change any):

- **The first message carries `<looks>`**: per moment, the setting, light and people words the must clips use (the
  commonest), because the consistency check needs them word for word and the plan's "first line of its design" alone cannot
  give them.
- **`finish` needs a blend note per cinematic clip** (a note that starts with its id), and one reason when there are none.
- **Anchors must be stage 1 clips**: a cinematic clip cannot anchor on another cinematic clip. `transition` may anchor on
  the neighbouring moment.
- **Role is not enforced**: only "differs from its anchor in role or technique" blocks (§3.5); the cinematic roles are in
  the prompt.
- **Reports on the locked must clips are counted, not listed** (run 3's 4 false screen-text reports), so they don't cost
  tokens every turn.
- **Money for 0d**: stage 2 passes stop at $1.50 in all and after 3 passes; a pass's run cap is $5 minus its stage 1 run's
  spend. `stage2 dry` on run 3: first turn worst case $0.49, a likely pass about $0.50 (a guess). The rehearsal's pretend
  total for 5 turns was $0.35.

# The product (phases 1-5, built offline 2026-11-08, uncommitted, $0 spent, no model called)

Phase 0e (one more paid lab run) was not run: it needs the person's yes. Phase 6 (the live trial) and 7 (the default) are the
person's. Everything below runs on scripted models; `docs/raphael/README.md` is the short map.

| Phase | What is built | Where |
|---|---|---|
| 1 Contracts | the wire (`ClipW`, `ExtraW`, `EditPlanW`, `ReviewRow`), the bin (`Clip` with `stage` / `anchor` / `blend`, ids and slates by code), `StoredRaphael`, the length cap type, `ProductionSettings.shot_planner` gains `"raphael"` and `raphael_length_cap` (1.5 / 2 / 2.5 / 3, default 2), job kinds, `AUTHORED` | `src/libs/contracts/raphael/{wire,bin,stored,scene}.py` + one line each in `production.py`, `jobs.py`, `build.py`, `staging.py` |
| 2 Checks | the lab's checks ported (not imported), screen-text rule out, the cap a parameter, stage 2's checks (anchor, blend, silent, differs from anchor, 3 a moment, cap), the moment review and blend-note checks, the variety REPORT (D-V: atmosphere > 2 or > 4 s, not blocking). Gold bins: run 3 (stage 1) and pass 5 (stage 2) | `contracts/raphael/checks.py`, `tests/raphael/fixtures/`, `tests/raphael/test_checks.py` (mutants for every rule, all four caps) |
| 3 Agents and system | `Agent.converse` + the `loop` agent shape (generic, in `core/agents.py`); agents `raphael_planner` (20 turns) and `raphael_cinematic` (12 turns); code tools `Stage1Session` / `Stage2Session`; `Meter` ($5 across both stages, price table, unpriced model refused); system `raphael_shot_planner` (stage 1, then stage 2 under one meter; D1 stop rules; `more_cinematic`; input hash includes the cap); the function `shot_planner_raphael` (port 8215, both job kinds); registration (task_manager, deploy workflow, start-functions, import-linter, langgraph.json); tier `raphael` (`OPENAI__MODEL_RAPHAEL`, default gpt-5 at high) | `agents/raphael/`, `systems/raphael/`, `src/services/shot_planner_raphael/`, `contracts/raphael/{tools,pack,money}.py` |
| 4 Storage | `Database/schema_v19.sql`, `upgrade_v18_to_v19.sql`, `supabase/migrations/20261108120000_raphael.sql`, pgTAP `019_raphael.test.sql`; `scenes.raphael`, `shots.planner` gains `raphael`, `shots.role / priority / slate / handle_in_s / handle_out_s / stage / anchor (slates) / blend`; the write step makes one shot per clip, binds each line to the must clip that performs it | `steps/raphael/raphael_write` |
| 5 API and interface | `GET /scenes/{id}/raphael`, `POST .../raphael/plan {cap?, note?}`, `POST .../raphael/cinematic {cap?}` behind `CanDirect`; the scene view's shots carry slate / role / priority / stage / anchor / blend. Interface: `src/features/raphael` (the Raphael tab: intended cut, the bin by moment, cinematic clips under their anchor marked *cinematic, optional* with blend and blend note, the moment review, the seconds against target and cap, what was left, a length-cap select beside Plan / Plan again / More cinematic), the production template gains the planner option and the length-cap select | `src/api/routers/scenes.py`, interface repo |

## Tests

* Backend: `tests/raphael` (96 tests: wire, checks, tools via the system, the lab's two rehearsals as product tests, the four
  caps, stage 2 failing / stopping / over the cap, run cap, no price, no model, the graph over fakes, the writer, isolation,
  removal, the service, the API, lab parity of the prompts, schemas and tool descriptions), the agents' and the step's own
  tests, and the generic contract tests now cover `loop` agents. `ruff`, `mypy` (1002 files) and import-linter are clean for
  everything new.
* Interface: `src/features/raphael` (15 tests); `npm run check` passes (376 tests).

## Choices the plan left open, made here (the person can change any)

* **A person's note** goes into the scene's context for the whole plan (Raphael has no revise pass to give it to).
* **Stage 1 stopped** (turns, run cap, error) with clips written: saved, marked `stopped`, stage 2 skipped (the recommended D1).
  With nothing to keep the job fails and names the classic planner. **Stage 2 stopped:** only the cinematic clips that pass the
  checks are kept (nice first when over the cap), each with a plain note written by code and honestly marked.
* **Chat Completions, not the Responses API:** the product loop goes through `core.llm` (LangChain `ChatOpenAI`), so the model's
  reasoning is not carried from one turn to the next as the lab's `previous_response_id` did. Cost and quality of that are for
  the live check (phase 6) to show.
* **Anchors on a shot row are slates** ("1A-1"), what the post team reads; the clip ids (c07) live in `scenes.raphael`.
* **Variety (D-V)** is in the stage 2 prompt and reported (atmosphere > 2 a scene, or a 8 s atmosphere clip), not blocking.
* **Stage 1's prompt** is `raphael_must.md` (S1), which was never paid for. Phase 0e should run it once before it is trusted.

## What is the person's

* Apply `Database/upgrade_v18_to_v19.sql` (not run; not tried against a local stack).
* D7: the model (`OPENAI__MODEL_RAPHAEL`; gpt-5 shuts down 2026-12-11; a model needs a price in `contracts/raphael/money.py`).
* Phase 0e (one lab run of S1 + the variety lines) and phase 6 (the live trial, two caps on one scene, the post team's verdict).
* S6 (the screen-text rule for the OTHER planners), L1/L2 as built, D1 as built, phase 7 (default; delete DaVinci's lab).

## Found on the way (not Raphael's)

* `tests/adam/test_system.py` and others fail on this machine only because `.env` has `ADAM_MODE=take`; they pass with
  `ADAM_MODE=staged`.
* `tests/adam/test_score_mutations.py::test_the_third_live_runs_plan_reads_far_below_the_master` fails on a clean checkout.
* import-linter's "david agents never import each other" is broken on a clean checkout (its `wire_schema` helper).
* A few tests in `tests/api` (a file-ticket URL on port 8001 from `.env`), `tests/parity` and
  `tests/hiru_ai/test_reader_ingest.py` also fail on this machine in a full run; they read the developer's `.env`, not
  anything Raphael changed (I checked the first two kinds; the parity ones I did not run on a clean checkout).
