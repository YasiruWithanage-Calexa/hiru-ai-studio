# Zora: what is built (plan/2026-11-06e)

Status 2026-11-07: **phases 0, 1, 2, 4, 5, 6, 7 and 8 built offline; the lab of phase 3 built but not run; phase 9 is
the person's.** No model was called, nothing was deployed or applied to the hosted database, nothing is committed.
Zora is off (`ZORA__ENABLED=false`) until a person turns it on (D3).

**Read this first: the prompts are not proven.** The plan orders the lab (Phase 3) before the system, and Phase 4 is
meant to use "the lab's winning prompts". On 2026-11-07 the person asked for the rest of the plan to be built, so Phase
4 uses arm A (one author: this plan's design and D2's recommendation) with the lab's prompts as they stand. The lab's
paid run, the blind A/B read and the Phase 9 replay still decide whether those prompts hold; arm B (Nova's seats) is not
built into the product. Turning Zora on before the lab has run is a person's call.

## Phase 0: evidence (free)

- `tests/eval/zora/fixtures/{episode1,arrival,father_refuses}.json`: the three scenes and the cinematic lab's mended
  plans (runs 14, 15, 16), copied by `lab/zora/build_fixtures.py` (the lab's run folders are not in git). No model call.
- `tests/eval/zora/cases.json`: the plan's ten requests plus two from its G2 examples ("move the turn earlier", a
  sequence's colour), 7 tune / 5 held-out, each with the conductor's answer as it should be (hand-written), what today's
  chat does with it, and expectations. `expect.needs` marks what only a model run can check.
- What today's chat does, per case (`old_chat` in the cases), read from its code rather than replayed: its replay
  harness needs a recorded model answer per case and a `shots`-rows fixture, and its kernel has no field for any of the
  plan-level requests. The code confirms G1–G7: `scene_kernel.MODEL_OPS` has no lens, angle, treatment, arc, sequence,
  colour or staging operation; nothing under `systems/director_chat` or `steps/scene_kernel` reads `scenes.jonathan`;
  there is no undo endpoint.
- **Not done:** step 3 (read two stored director threads from the dev database for real phrasing). It needs the
  person's yes to read the hosted database.

## Phase 1: the document and the kernel (free, offline)

| File | |
|---|---|
| `src/libs/contracts/zora/ops.py` | the grammar of §4.2: every op, who may use it, `path_of` (one address space for locks, ownership and no-ops), `shot_number` ("S03", "3", 3), `infer_op`, `invented` (Nova W4 + its trimming fix) |
| `src/libs/contracts/zora/doc.py` | `ZoraDoc` (plan, scene, `Person{locked, settled}`), `shape_errors` = the planner's wire validation in pure code |
| `src/libs/contracts/zora/render.py` | `addressable(doc, only=…)` with the header that names every field and op; `consumer(doc, only=…)` |
| `src/libs/hiru_ai/steps/zora/zora_kernel` | `ZoraKernel`: handles, batch-start addressing, exact undo, one-op rollback, removals whole or not at all, locks (author refused; conductor and person pass and lock what they set), lines bound by code, script/translation/marks ops **staged**, never applied. The step adds the planner's own validation by id (`jonathan_check` → `malformed`) |

Tests: `tests/zora/test_ops.py`, `tests/zora/test_kernel.py` (Nova's lessons pinned: W1 named ranges, post-op numbers,
two inserts in one batch, W3 removals, exact undo on all three plans, a lock follows its shot through renumbering, no
path writes a line's words).

## Phase 2: deps, board, ledger, delivery (free, offline)

| File | |
|---|---|
| `src/libs/contracts/zora/effects.py` | `WRITES` (effect → label, owner, ops), `normalize_effect`, `changed_effects` paired by handle |
| `src/libs/contracts/zora/tasks.py` | `Task` (must `writes`, may `may`, `scope`), `merge_tasks` |
| `src/libs/contracts/zora/ledger.py` | `Ledger`: `event()` (`nothing_changed` explicit), `gate()`, `context()` (Nova's blocks: done, refused, team refused, asked-for-not-done, overruns, NOTHING CHANGED only when the turn tried) |
| `src/libs/hiru_ai/steps/zora/zora_deps` | the stale table of §4.3, `stale`/`joins`/`end_touched`, the re-cut guard (ratio 0.5, min 3; `shape` and a forced lane exempt) |
| `src/libs/hiru_ai/steps/zora/zora_board` | `settle`: allow-list by effect and scope, locks with the person's words ("you set S03's lens yourself"), no-op dropped first (noise, never reported), lines refused. `gate.py`: `jonathan_mend` + `jonathan_check` by id, `new_problems` by a handle-stable key, `protect` (a take the person set is put back and the overrun reported), `overruns`, `seams` |
| `src/libs/hiru_ai/steps/zora/zora_deliver` | `undelivered` (by handle, in scope), `retask` once, `report` (a locked or person-only effect is reported, never re-tasked) |
| `src/libs/hiru_ai/steps/zora/zora_ledger` | `change_lines` by treatment / sequence / shot / staging / end state, numbers as the person now sees them |

Tests: `tests/zora/test_render_effects.py`, `test_deps_board.py`, `test_gate_deliver_ledger.py`, `test_cases.py` (each
case's recorded conductor answer through the real kernel and deps), `test_isolation.py`, `test_removal.py`; each step's
own `tests/`.

## Phase 3: the lab (built, NOT run: needs the person's yes)

`lab/zora/` (README, prompts, `run.py`, `turn.py`, `schema.py`, recorded answers, tests). Money rules are code:
`BUDGET_USD = 3.00`, worst-case guard per call, cache by request hash, ledger, `--hypothesis` after the first run.
Arm A (one author on `gpt-6.1-sol`, low effort, Jonathan's prompt as the primer) and arm B (four seats on `gpt-5-mini`)
run on the same recorded conductor answers; the conductor is scored on its own. `run.py offline`: 7/12 pass on
recorded answers, and the 5 without an answer are reported as not done, never claimed.

**Cost (estimated by `run.py cost`):** arm A on the 7 tune cases ≈ $0.73 likely / $1.65 worst; arm B ≈ $0.22 / $0.54;
arm A on the 5 held-out cases at k=3 ≈ $1.18 / $2.60. $3 holds one comparison plus the winner's held-out check, with
little room for prompt changes.

## What differs from the plan's text, and why

- **The kernel's planner validation runs by id through `jonathan_check`'s `malformed` answer**, on top of a pure-code
  copy of the wire's types and closed lists (`shape_errors`): contracts may not import another group's contracts.
- **Problem keys carry shot numbers** (`clock:15`), which shift on an insert, so "only new problems count" compares a
  key with its shot numbers turned into handles (`gate.stable_key`). Without it an insert made every later problem look
  new.
- **A take the person set wins over the mend**: the mend's longer take is put back and reported as an overrun with the
  way out (§4.6.6 says report; the mend alone would silently override the person).
- **Removing or moving a shot that shows the script is refused** ("merge it instead"): a removal would drop lines and a
  move would put them out of order. Only added shots move or go.
- **Auto-lock on what the person sets** is limited to field edits (`ops.LOCKING`); structural ops and arc entries are
  not locked (arc numbers shift).
- **`Task` lives in `contracts/zora/tasks.py`**, not in the deps step: two steps of a layer may not import each other.
- **`end.set` is the person's only** (conductor and person), as the plan's table says; the effect `end_state` is
  reported, never re-tasked to the author.
- **The vocabulary is copied** from the planner (sizes, links, takes, added kinds) and a test checks it never drifts.

## Phase 4: the system `zora_chat` (offline; tests use scripted models)

| File | |
|---|---|
| `agents/zora/zora_conductor` | the small transcriber (`medium`): the lab's charter to the letter (a test compares them) |
| `agents/zora/zora_author` | the one author, new tier `zora` = `model_jonathan` at `effort_zora` (default low, D7): Jonathan's author prompt to the letter, then the lab's Zora charter (a test checks both); the user message is the lab's `author_message`; `production_memory`, `memory: ["*"]` |
| `agents/zora/zora_reply` | the reply (`medium`, streamed), written from the ledger, read last |
| `contracts/zora/wire.py` | the strict answer shapes, MOVED from `lab/zora/schema.py` so the lab and the product send the same bytes |
| `contracts/zora/events.py` | the events, `ZoraAction` / `ZoraActionResult`, `Revision` |
| `steps/zora/zora_guard` | the old chat's guards, COPIED: confirmations and undo phrases in code, the loop breaker, the reply guard (a card that is not there, a promise nothing backs, a change the ledger does not show, any offer to trim a line), the template reply from the ledger |
| `systems/zora/zora_chat` | `graph.py` (read → in_code → conduct → quiet or edit → settle → reply), `turn.py` (the lab's pipeline plus the conductor's checks, the save and the reply), `actions.py` (use, undo, redo, lock, unlock: no model), `scene.py`, `store.py` |

The conductor's answer is checked in code and retried ONCE, told what was wrong (appended last, the cached prefix
unmoved): a writing lane with no op and no task (W6), an op whose words the person did not say (W4), an unknown effect.
Confidence below 0.5 on a writing lane becomes `clarify`; a failed router call is `clarify`. Settings `ZORA__*`
(`core/settings.ZoraSettings`): `MAX_REPAIRS` 2, `DELIVERY_PASSES` 1, `RESHAPE_DIRTY_RATIO` 0.5, `RESHAPE_MIN_SHOTS` 3,
`VARIANTS_MAX` 3, `AUTHOR_TOOL_CALLS` 6, `TRANSCRIPT_MESSAGES` 4, `REVISIONS_KEPT` 30. Without a model key undo, redo
and confirmations still answer; anything else says Zora needs its model.

## Phase 5: save, undo, seams

- `steps/zora/zora_save`: the edited plan goes through **Jonathan's own write path** (`jonathan_write`, by id), so a shot
  is stored with the card, intent, finished camera design and current pins the planner would give it; every shot that
  was there before the turn gets its **old id back** (by kernel handle), so frames and prompts stay attached and the
  API's pins report them out of date.
- Optimistic check: a save over a plan someone changed since the turn read it is refused and said so.
- Revisions (`scene_plan_revisions`): `base` (the plan before the first Zora change), `turn`, `use`, `undo`, `redo`;
  `logic.Stack` replays them (redo is the undo of an undo; a new change clears redo); the last 30 are kept. An undo
  whose head is not the plan on the scene (a Jonathan re-plan landed) is refused rather than jumping over it.
- Absent-safe: without the table the edit stands and undo says it is not available yet.
- Seams: when the end state changed and the next scene carries on from this one, `jonathan_seams` judges the join.
- Database: `schema_v14.sql` and `upgrade_v13_to_v14.sql` (v14 is unreleased, so folded into the same pair as the
  video work), `supabase/migrations/20261106185010_zora_revisions.sql`,
  `supabase/tests/database/016_scene_plan_revisions.test.sql`. **Not applied to the hosted project.**
- `StoredPlan` gains `person: {locked, settled}` and `pinned` (inside the `scenes.jonathan` JSONB: no column change);
  Jonathan's graph carries `person` over a re-plan.

## Phase 6: treatment mode and the pinned-treatment Jonathan run (D5 taken as recommended)

- `contracts/zora/treatment.py`: gaps (hard: the arc does not cover every block; soft: approach, colour script,
  geography, key image), `settled`, suggestions ("Draft the arc", "You decide the rest", "Plan shots from this
  treatment"). A suggestion is matched in code (no router); "You decide" settles the soft gaps and the reply is told
  never to ask about them. With no shots only treatment and sequence operations pass.
- The plan's one change inside the Jonathan group: `jonathan_pack` prints a pinned treatment as fixed
  (`<pinned_treatment>`; none = the pack byte for byte as before), `jonathan_check` code `treatment`
  (`checks.treatment_drift`) reports a plan that drifts from it; the graph reads `state.pinned[scene_id]` or the
  scene's stored `pinned`.

## Phase 7: the function and the API

- `src/services/zora_chat` (`hiru-zora-chat`, port 8213, 300 s): a thin handler; a turn streams, `{"action": true}` is
  plain JSON. Registered in `task_manager.ZORA_CHAT`, `start-functions.ps1`, `deploy-functions.yml`, `langgraph.json`,
  `pyproject.toml`.
- `api/routers/zora.py`, `api/services/zora.py`: `GET …/scenes/{id}/zora`, `POST …/zora/turn` (stores the message first;
  the classic chat's main thread), `…/zora/undo|redo|lock|unlock` and `…/messages/{id}/use` (Permission.DIRECT),
  `…/zora/plan-shots` (a Jonathan job, treatment pinned). Routing (D3): Zora answers only when `ZORA__ENABLED` and the
  scene holds a Jonathan plan, else 409 with the reason; the classic `/chat` is unchanged. The API's undo replay is held
  to the function's by a test. `contracts/director.ChangesBlock` stores the ledger under each reply.

## Phase 8: the interface (`hiru-ai-studio-interface/src/features/zora/`)

`ZoraChat` takes the chat's place on the Director page when the scene is Zora's: "What changed" under each reply,
Undo / Redo, amber gate warnings, the re-plan offer (Re-plan with Jonathan / Keep the plan, through the existing "plan
again with a note" endpoint), proposals through the existing `OptionsCard`, suggestion buttons, locked fields a person
lifts, `@` for shots and sequences. Tests: the ledger mapper and `WhatChanged`. **D8 is open: no Figma frames were
made**; the panel uses the classic chat's layout and tokens. Locking a field from the shot details is not built (the
API and the panel's unlock are).

## What differs from the plan's text (phases 4 to 8), and why

- **No lab winner yet**: arm A's prompts (see the top).
- **The author has no read tools in v1**: its `with_tools` form waits for a live eval (CLAUDE.md); the scoped plan is in
  its prompt.
- **Translation is routed to the classic chat**: the translator's card is built on the old kernel's script ops and its
  choice path; copying it would copy the old kernel. The `translate` lane says where to go (loop breaker included).
- **`StoredPlan.previous` is not overwritten** (§4.7): Jonathan uses it for the side-by-side with the earlier shot list;
  the last plan lives in the revisions.
- **Zora reads the scene through Jonathan's system by id** (`parts.module("system", "jonathan_shot_planner", "scene")`),
  so blocks, line ids, cast and place are exactly the planner's.
- **The API never imports `contracts.zora`** (the isolation test): plain JSON, and a ten-line undo replay held to the
  function's by a test.
- **Advisors are off** (D6 as recommended); the lead persona is the reply's voice.

## Outside the group (one line each, as §4.0 lists)

- `pyproject.toml`: import-linter independence for the seven steps, the agents and the systems; `zora_chat` in every
  service list.
- `tests/jonathan/test_removal.py`: the Zora files that name Jonathan's parts by id (kernel step, gate, save step, the
  system's scene reader, the author's prompt test, the API's plan-shots route and its test).
- Jonathan itself (Phase 6, D5): `contracts/jonathan/stored.py` (`person`, `pinned`), `contracts/jonathan/checks.py`
  (`treatment_drift`), `jonathan_check/step.py`, `jonathan_pack` (`pinned_part`), the system's `graph.py` and
  `scene.py` (the pin and the locks carried).
- Core: `core/models.yaml` (tier `zora`), `core/settings.py` (`effort_zora`, `ZoraSettings`), `core/ports.py`
  (`RevisionStore`), `core/context.py` (`Ports.revisions`), `core/fakes.py` (`FakeRevisions`),
  `adapters/supabase_rest.py` (`SupabaseRevisions`).
- `contracts/director.py` (`ChangesBlock`), `api/` (router, service, config `ZORA__ENABLED`, `ZORA_CHAT`,
  `RevisionsRepo`), `tests/api/fakes.py`, `.env.example`, `langgraph.json`, `scripts/start-functions.ps1`,
  `.github/workflows/deploy-functions.yml`, the database pair, `CLAUDE.md`, `docs/AI_CATALOG.md` (regenerated).
- `tests/jonathan/test_removal.py` had an unresolved stash-merge conflict when this work started (both sides kept).

## Checks (2026-11-07, phases 4 to 8)

`ruff check src tests scripts` clean; `mypy` clean (907 files); `hiru_ai validate` 168 parts, 0 errors; `hiru_ai catalog
--check` current; `scripts/lint_imports.py` 39 kept, 1 broken (David's agents contract, broken before this work; every
Zora contract kept). `pytest -q` (key blank): 4542 pass, 20 fail, the same 20 as on 2026-11-06 below (`tests/adam` 11,
`tests/api` handoff/looks/production 6, `tests/parity` 3), none in Zora or what it touches. `npx supabase test db`: 17
files, 214 tests pass (016 new); `npx supabase db advisors`: no issues; the v14 dump comparison is in
`Database/README.md` (v14 = v13 + upgrade; the Zora table identical in all three; two older column-order differences
reported, not touched). Interface: `npx next typegen && npm run check` pass (26 files, 197 tests); `format:check`
fails on 203 files that were already unformatted, none of them this work's (the Zora files and the two edited ones pass).

## Checks (2026-11-06)

`ruff check src tests scripts` clean; `mypy` clean (868 files); `hiru_ai validate` 162 parts, 0 errors;
`hiru_ai catalog --check` current; `scripts/lint_imports.py`: 37 kept, 1 broken, **the broken one is David's agents
contract, already broken before this work** (`david_repair` imports the group's `wire_schema`); Zora's is kept.
`pytest tests/zora src/libs/hiru_ai/steps/zora tests/jonathan/test_removal.py tests/jonathan/test_isolation.py
tests/test_isolation.py`: all pass; `pytest lab/zora/tests`: 8 pass. Full suite (`pytest -q`, key blank): 4306 pass,
21 fail, none in Zora or what it touches: `tests/adam` (11), `tests/api` handoff/looks/production (6) and
`tests/parity` (3), all in parts this work does not change (known on this machine: the developer's `.env` sets
`ADAM_MODE=take`; the parity recordings are another plan's work in progress).

## Open, the person's

1. **The lab's first paid run** (D2, D10): `lab/zora/run.py paid --yes --arm A --split tune`, then arm B, then the blind
   read (`compare`). Each run needs a yes.
2. Phase 0 step 3: reading two stored director threads from the dev database (read-only), if wanted.
3. Applying `Database/upgrade_v13_to_v14.sql` (or `schema_v14.sql`) to the hosted project: until then Zora runs
   without undo and says so.
4. Turning Zora on (`ZORA__ENABLED=true` for the API and the `zora_chat` function, D3), ideally after the lab.
5. D8: Figma frames for the ledger, undo, the re-plan card and the suggestions (the panel is built without them).
6. D6, D7, D9 as recommended unless the person says otherwise (advisors off, the `zora` tier at low effort, no RAG
   craft notes).
7. Phase 9: `scripts/replay_director.py --engine zora` (not built: it needs the lab's recorded answers to be worth
   anything), a director on five real scenes, then D3's default and the old chat's retirement.
