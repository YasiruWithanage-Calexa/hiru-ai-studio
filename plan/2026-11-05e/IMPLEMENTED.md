# Shot Planner David: what is built (plan/2026-11-05e)

Status 2026-11-05: **Phases 0 to 5 are built offline** (nothing here has called a real model, and nothing has been run on the
hosted database). The spike (Phase 2's run), the blind comparison (Phase 6), the decisions D2 to D7 that wait on them, the
default (Phase 7) and running the migration on the hosted project are a person's. Nothing is committed.

## What a person does next

| Step | Command / place | Costs |
|---|---|---|
| 1. Paste one ChatGPT answer per scene (D10) | `tests/eval/david/chatgpt/<scene>.txt` | 10 minutes |
| 2. Run the spike | `.venv/Scripts/python.exe scripts/david_spike.py --yes` (add `--c-model <model>` for configuration C, `--scene-dir <folder>` for real Hiru scenes, D6) | about $5 to $10 |
| 3. Read the table and the side-by-sides | `tests/eval/david/spike/summary.md`, `tests/eval/david/spike/side_by_side/<scene>.md` | free |
| 4. Early stop (D10, rule 8) | if David is clearly behind ChatGPT on most scenes: change `david_author/prompts/system.md` or the pack, run step 2 again. **Do not add an agent.** | |
| 5. Decide D2 (JSON directly or free text first) and D3 (model and effort) | `OPENAI__MODEL_AUTHOR`, `OPENAI__EFFORT_AUTHOR`, `OPENAI__EFFORT_REPAIR` in the environment | |
| 6. The blind comparison (Phase 6) | `scripts/david_compare.py`, then a Hiru director fills `tests/eval/david/compare/<scene>/blind.html` | a director's time |
| 7. Apply the database change (D7) | `Database/upgrade_v11_to_v12.sql` (David is folded into v12, which the plan recommends while v12 is unapplied; if v12 has already been run on the hosted project, split it into a v13 pair instead). The migration and its test are `supabase/migrations/20261105120000_david.sql`, `supabase/tests/database/013_david.test.sql` | |
| 8. Choose the default (Phase 7) | `settings.shot_planner = "david"` per production; retiring Adam is a separate plan | |

The plan said Phase 2's exit comes before Phases 3 to 5 are built (D10's early stop). They were built offline anyway, as for
Adam: the prompt and the pack can still change after the spike without touching a part, because the failure paths, the writer
and the system are scripted-tested and do not depend on how good the author's prose is.

## Phase by phase

**Phase 0, the pattern and the folders.** `docs/AI_PATTERN.md` (the eight rules and the call budget), `docs/adr/0010-one-author-pattern.md`,
the `david` group folder in each of the six `hiru_ai` layers (`group.yaml`, and the removal list in the `systems` one),
import-linter contracts that keep David's parts independent of each other, `tests/david/test_isolation.py` (a David part imports
only its group, a lower layer's group, the core, the rag, `contracts`, and the clip schema of the shared `serialize` step; nothing
outside the group imports into it) and `tests/david/test_removal.py` (`hiru-ai remove --group david` lists exactly §4.0).

**Phase 1, contracts and code.** `contracts/david/`: `plan.py` (the closed lists, `Problem`), `wire.py` (`DavidWire`, `PatchWire`;
what the author and the repairer write, and `patched`), `stored.py` (`scenes.david`), `scene.py` (the scene as David is given it
and the Veo clock over a shot), `checks.py` (every check of §6), `mend.py`, `links.py`, `seams.py`. Steps: `david_check`,
`david_mend`, `david_links`, `david_seams`. `tests/david/test_checks.py` writes the phone call as a David plan by hand
(`tests/david/gold.py`): it passes every check and the mend changes nothing; mutants (a dropped line, a line twice, an invented
person, a take too short, a teleport, the caller in frame, other clothes across a seam) fail with the right sentence and the
right owner; across the five gold scenes the mend never deletes a block or a line.

**Phase 2, the author, the pack and the spike.** `david_pack`, `david_author` (prompt 1,833 words with ONE worked example, the
`refuses_money` scene, validated against `DavidWire`; tier `author`; the answer's schema is `DavidWire` with the clip schema of the
`serialize` step in place of the free `ir`), scripted eval cases for both agents, `scripts/david_spike.py` (refuses without `--yes`;
configurations A, B and C; saves plans and usage; prices them; writes the side by side with a pasted ChatGPT answer, D10) and
`scripts/david_compare.py` (the plain shot lists and the blind page; Phase 6's tool, built here as the plan asks).

**Phase 3, repair and the system.** `david_repair` (tier `repair`), `david_write`, the system `david_shot_planner`
(`scene.py` the per-scene pipeline, `graph.py` the pool, chains, budget, reuse, cascade and edits), the Cloud Run function
`src/services/shot_planner_david` (port 8210), the job kind `plan_scene_david`, `settings.shot_planner = "david"`,
`settings.david_order` (D5), `OPENAI__MODEL_AUTHOR` / `EFFORT_AUTHOR` / `EFFORT_REPAIR`, `DAVID_WORKERS`, the two tiers in
`models.yaml`, registration in `task_manager.FUNCTIONS`, `deploy-functions.yml` and `scripts/start-functions.ps1`, and the
migration. `tests/david/test_system.py` (25 tests): a clean scene makes one call; a crowded shot is mended with no call; a wrong line
triggers one repair; two failed repairs are reported, not failed; a chain passes its end state and its last shot (word for word) on,
also across a fresh delivery; in `episode` order a replan cascades until an end state comes out the same and an approved scene
stops it; the budget cuts a chain and the next delivery carries on from `scenes.david`.

**Phase 4, the shot producer reads David's design.** `"david"` joins `AUTHORED` (`contracts/staging.py`, one line: the legacy
engine and the part both read it). `tests/david/test_producer.py`: a David shot's design is not stale, the intent agent is skipped
for its shots and its scene, the shot producer designs nothing and calls no model for a David scene, a person's camera override
still wins, and the Veo prompts the serialize step writes in code from the author's IR pass `prompt_lint`.

**Phase 5, API and the David tab.** `GET /scenes/{id}/david`, `POST /scenes/{id}/david/plan` (`{note?}`) and
`POST /scenes/{id}/david/added/{n}/remove`, behind `CanDirect` (`tests/david/test_api.py`). The interface (`hiru-ai-studio-interface`)
has `src/features/david/` and mounts it as the **David** tab beside Adam's; the production template can pick David as the planner.

## Where it differs from the plan

- **`added[].object`** (one more field) so the check "an object not in the script or the place card" has something to read.
- **`PatchWire.staging`**: the repairer can send a complete new staging map; a teleport, a crossed line or an eyeline can be mended
  only there. The plan's patch had shots and an end state.
- **Prompt lint is not a check of its own.** `david_write` stores the design, and the lint runs in `tests/david/test_producer.py`
  over the prompts the serialize step writes from the author's IR; a failing prompt is a bug in the writer, not a finding for a repair.
- **Look at the start of an episode** comes from the canon card's `wardrobe_anchor` or appearance, not from the `canon_looks` table.
  A look change inside a chain is carried by the end state; the entries in `scenes.david.look_changes` are for the tab and the pack.
- **A staging teleport is repaired by the author**, not with the `move:<who>` bridge; the rules-only bridge belongs to the classic engine.
- **Seams** compare a scene's first marks, hands, clothes and light (and what it was planned from) with the end state before it; the
  look comparison is loose (a third of the smaller description's words in common), so it reports a change of clothes, not wording.
- **Production memory** (plan 2026-11-05d) is not read yet: `production.rules` holds only the banned terms. The pack has the place.
- **Real scenes (D6)** are not in the repository. `scripts/david_spike.py --scene-dir <folder>` takes them in the shape of
  `tests/eval/david/scenes/*.yaml`.

## Verified

`ruff check` on every David file and on the files this plan changed, `hiru-ai validate` (148 parts, 0 errors),
`scripts/lint_imports.py` (31 contracts kept), `hiru-ai eval david_author david_repair` (scripted, 4 of 4), `tests/david` (121 tests),
the interface's `tests` for the David feature (10). **Not verified here:** the SQL (`supabase db reset` and `supabase test db`
need Docker and the local stack; run them, and compare the three dumps as `Database/README.md` says), and anything that needs a
real model: the prompt's quality, the author's timing (600 s timeout), the cost estimate ($0.17 to $0.27 a scene) and the gate.
