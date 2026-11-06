# Zora: what is built (plan/2026-11-06e)

Status 2026-11-06: **phases 0, 1 and 2 built offline, and the lab of phase 3 built but not run.** Nothing is wired into
the product (no system, service, API, database change or screen), no model was called, nothing is committed.

Why it stops here: the person's rule is to prove the prompts in a small lab with a hard budget before the full system is
built (`feedback: prove before building`), and the plan orders it the same way (§2 rule 4: "the prompts are proven in a
lab ... before the system is wired"; Phase 4 uses "the lab's winning prompts"). Phase 4 onward waits for the lab.

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

## Outside the group (one line each, as §4.0 lists)

- `pyproject.toml`: an import-linter independence contract for the five steps.
- `tests/jonathan/test_removal.py`: the two Zora files that name Jonathan's parts by id are on its list.
- `docs/AI_CATALOG.md`: regenerated.
- Not touched yet: `CLAUDE.md` (uncommitted work of another session is in it), `api/`, settings, `.env.example`,
  `langgraph.json`, the function scripts and the database pair (later phases).

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
3. D3–D9 as in §7 (scenes that use Zora, the undo table, treatment mode, advisors, models, Figma frames, RAG).
4. Phases 4–9 after the lab: the system, save/undo with the v14 migration (applied by the person), treatment mode,
   the API, the interface, the live check.
