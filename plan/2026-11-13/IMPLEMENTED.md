# plan/2026-11-13: what was built (2026-11-13)

Phases 1 to 7 are built offline, uncommitted, in both repos. Phase 8 (Sable through the row kernel) is NOT built: it
is split out (D-D). Phase 9 (live check) is the person's. No model was called and nothing touched the database.

Decisions taken as recommended: D-A (take → `duration_locked`, other fields → `person_edits.zora_locks`), D-B (the
silent shot: found by code every turn, offered as a one-click card, never fixed silently; asked by message, saved at
once), D-C (a pre-plan revision holding a planner's JSON is not restorable: undo stops there and says why), D-E.

## Backend

| Phase | Where | Notes |
|---|---|---|
| 1 | `src/libs/contracts/coverage/` (`scene.py`, `checks.py`, `risk.py`, `ledger.py`) | `Coverage.from_rows(scene, shots, lines, characters)`; `row_of` writes a whole row back (every column carried through; word target, words, speaker follow the clip). `line_unvoiced` (fix `code`), `unvoiced()`. `lock_key` lives in `scene.py` (contracts cannot import a step). |
| 1 | `contracts/costs.py` | `gpt-6.1-terra` is in `UNSEEDED_PRICES` / `LIST_PRICES`, NOT `SEED_PRICES`: the migration test holds `SEED_PRICES` to `upgrade_v16_to_v17.sql`, and no migration was written. The budget prices with `LIST_PRICES`. |
| 1 | `contracts/producer.py` | `PersonEdits.zora_locks` (+ `dump`). |
| 2 | `src/libs/hiru_ai/steps/coverage_kernel/` | **Ungrouped**, not `steps/coverage/coverage_kernel`: the registry refuses a `coverage` group (the `coverage_critic` agent already carries that prefix) and a grouped system may only name its own group's parts, so the step is shared and `systems/zora/group.yaml` lists it under `shared`. `sound_mode` op; a moved line is voiced by sight (dialogue / voiceover), and the clip it left goes back to ambient; a non-voiced mode on a performing clip is refused. Writers: `conductor`, `person` (lock what they set), `code` (no lock), `author`, `repair`. |
| 3 | agents `zora_conductor` / `zora_author` / `zora_reply` (v2) | Lab prompts + the `sound_mode` op; author has the safe-depiction line and no planner prompt. Conductor gains `production_memory` + `memory: ["*"]`. Tiers `zora_chat` (gpt-5-mini minimal), `zora_author` (gpt-6.1-terra low); `zora` tier and `effort_zora` gone; `ZoraSettings`: `turn_cap_usd = 0.02`, `variants_max = 2`. |
| 3 | `core/agents.py`, `core/llm.py`, `core/middleware/base.py` | `Agent.run(max_output=)`, `Agent.stream(max_output=)`; `get_llm` / `get_structured(max_tokens=)`; `ModelCall.max_output`. |
| 3 | `systems/zora/zora_chat/budget.py` | `Budget.watch(ctx)` tees the turn's usage rows; `output_cap` prices the input first; `OverBudget`, `CutOff`. |
| 4 | `systems/zora/zora_chat/` `turn.py`, `scene.py`, `store.py`, `actions.py`, `graph.py` | The lab's turn on the ports. `quick()` reads size / take / remove and "fix the silent shots" with no model. Cards are `confirm` blocks on the reply message; Accept / Reject / Use are actions (no model for the change; Zora's sentence after it is the reply agent inside the same budget, else code). Save in place: changed rows only, ids kept, `version + 1` on touched clips, renumbered, new clips with a uuid, the scene's planner value and `draft`; a clip whose IR changed is finished with `serialize.shots.finish` and its design written in the same upsert (not a separate `save_design` call). Revisions store `{rows, lines}`. Models are a seam (`ask`, `say`) so tests replay recorded answers. |
| 5 | removed | `steps/zora/*` (all seven steps), `contracts/zora/{doc,effects,ledger,ops,render,tasks,treatment}.py`, `tests/eval/zora`, the Jonathan-shaped tests; the Zora entries in `tests/jonathan/test_removal.py`; the zora steps contract in `pyproject.toml`. `tests/zora/test_isolation.py` now fails on any planner named as a code identifier in a Zora file. `lab/zora` (the old lab) still imports the removed modules: it is evidence, not run. |
| 6 | `api/routers/zora.py`, `api/services/zora.py`, `contracts/zora/events.py` | `POST …/zora/accept` and `/reject` `{message_id, block}` (CanDirect; approved scene → 409; a card from another scene → 404); `plan-shots` dispatches `build_pipeline(shot_planner)[-1]`; status reads locks from the rows. `ZoraAction.kind` gains accept / reject; `ZoraActionResult.message`. |

Tests: `tests/zora/test_rows_coverage.py` (the lab's tests on the product modules + §3.7), `test_rows_scenario.py`
(the twelve lab turns replayed with run 6's recorded answers: lanes, saves, cards, Accept, undo, Reject, cannot,
insert, options, Use this; plus a stale card), `test_rows_turn.py` (silent card, sound fix by message, save in place,
optimistic check, D-C, roles, no model, budget cap / refusal / cut-off / reply in code, guard), `test_api.py`,
`test_stop.py`, `test_isolation.py`; the step's own tests.

## Interface (`hiru-ai-studio-interface/src/features/zora/`)

`components/confirm-card.tsx` (+ test): why it asks, what would happen, Accept / Reject, settled as "Accepted ·
revision N" / "Rejected"; the sound fix is the same card titled "Fix the sound". `zora-chat.tsx`: renders it, settles
it in place and appends Zora's sentence; treatment chips, `confirm_reshape` and "Re-plan with Jonathan" gone; "/replan"
asks, then re-plans with the production's planner. A risky option says "Needs your OK: …" on its card (`impact`, set by
the backend). No costs anywhere.

## Checks (2026-11-13)

Backend full `pytest` (`ADAM_MODE=staged OPENAI__API_KEY=`): 5611 passed, 28 failed, 3 errors. All 31 are
pre-existing: the same tests fail on a clean checkout of HEAD with the same `.env` (13 of them only because the
`.env` sets the files URL to port 8001; the rest also fail on HEAD without it). Zora's own tests and the agents' and
step's tests all pass.

Backend: ruff clean on every file this plan touched (4 long lines remain in files it did not touch); mypy clean;
`hiru_ai validate` 0 errors; `catalog --check` current; import-linter 2 broken contracts, both pre-existing
(`api.services.media_thumbs`, David's agents). Interface: typecheck clean; one failing test,
`features/raphael/components/raphael-panel.test.tsx`, not touched here; prettier flags 43 files, none in
`features/zora`.

## Open

- Phase 8 (Sable's change cards through the row kernel): its own plan. Sable's cards carry the classic kernel's
  operations (`change_propose`, `plan_try`, the director function); porting them is more than a day.
- Phase 9 (live, the person's yes, cap $0.50).
- `lab/zora_rows/coverage.py` has an uncommitted `from_data` helper that is not from this build.
