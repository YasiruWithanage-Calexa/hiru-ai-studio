# plan/2026-11-23b — what was built (2026-11-23)

Built offline, both repos, uncommitted (on top of plan/2026-11-23, also uncommitted). No model call. One schema change:
**v30** (`Database/upgrade_v29_to_v30.sql`, `schema_v30.sql`): `token_usage_totals` also groups by phase and job. The
person had already applied v29, so v29 stays exactly as applied and v30 drops and re-makes the function (same
arguments, two more columns). Until v30 is applied the API sees the v29 function has no `phase` and sums the month's
rows itself, so "By purpose" is right either way. D6-D8 taken as
recommended: older rows without a scene go by their job or are shared by lines (no backfill); setup figures for
`VIEW_COSTS` holders; sheets told apart by their job (no `frame_render.sheet` phase yet).

## Phase 0 — the audit (read-only)

**Who writes `token_usage`.** Every Cloud Function builds its run context in one place
(`hiru_ai/adapters/supabase_rest.build_context`), so the `scene_id` on its rows came from `RunContext.usage_row`, which
added it only when `USAGE_SCENE` was on. It was off (not in `.env`, default false). Systems that put a scene on the
context: Raphael (`replace(ctx, scene_id=...)` per scene), Zora, Sable, the director chat, shot producer drafts. The
legacy director chat handler read `USAGE_SCENE` itself. The API's own rows (`search.embed / rerank / answer`) carry a
production only. Scene-scoped work that does not set the context's scene (design, prompts, first frames, boards) is found
through its job, whose request names `scene_id`.

**Jobs.** A build is ONE job row with several hops (structure build → breakdown → script split → Raphael), so the job's
kind does not say which step a row came from: the phase does. Requests: `doc_ingest` names `document_id`; a re-plan
(`plan_scene_raphael`, `cinematic_scene_raphael`) names `scene_id`; sheet paintings are `frame_render` jobs naming
`entity_id` (character / face sheet, `routers/canon.py`) or `look_id` (look sheet, `routers/looks.py`); a board, a frame,
prompts and a design name `scene_id`. `canon_refine` jobs run the breakdown's agents (`breakdown.*` phases).

**Links.** `episodes.source_document_ids` ties a document to the episodes built from it; `scenes.episode_id` ties a
scene to its episode. No schema change is needed.

**The table** (every phase prefix in the code; `tests/contracts/test_cost_parts.py` fails on a new one):

| Part | Phase prefixes | Job overrides |
|---|---|---|
| production setup | `canon_extract`, `breakdown.canon`, `breakdown.looks`, `breakdown.series`, `search` | any `canon_extract` / `canon_refine` job; a `frame_render` job naming `entity_id` or `look_id` |
| episode setup | `doc_ingest`, `breakdown` (the rest), `script_split`, `structure_build`, `raphael`, `adam`, `david`, `jonathan` | |
| scene | `director`, `zora`, `sable`, `shot_producer`, `camera_agent`, `shot_prompter`, `frame_render`, `video_render` | |

## What changed

- **Switch removed** (phase 1): `USAGE_SCENE` / `usage_scene` gone from `core/settings.py`, `core/context.py`,
  `adapters/supabase_rest.py`, the director chat handler, `.env.example`, `Database/README.md`. A run with a scene
  always writes it.
- **`contracts/cost_parts.py`** (phase 2): `part_of`, `sheet_kind`, `episodes_of`, `share` (by dialogue lines, exact
  sum), `setup_figures` (production entries by kind; episode entries: "Upload and first plan", "Re-plan, scene N",
  "More cinematic, scene N", "Document read again", "Production build, shared by lines"), `PurposeTotals`.
- **Scene ≈** (phase 3): only rows whose part is `scene`; the episode share (`EPISODE_PHASES`, `unassigned_usage`) is
  gone; sheet jobs are kept out of the "what a frame costs" median; **no retry margin**: `with_retry` and
  `Margins.retry_bp` removed, `margins.yaml` lost `estimate:`, and a file that still has it is refused by name.
- **Setup routes** (phase 4): `GET /v1/productions/{pid}/setup-cost`, `GET .../episodes/{eid}/setup-cost`
  (`VIEW_COSTS`, 60 s cache cleared when a job ends; `{currency, total_micros, complete, entries[{label, at,
  total_micros, complete}]}`). Repos: `costs.jobs_of`, `costs.production_usage` (paged); the memo knows the new reads.
- **Usage by purpose** (phase 5): every group carries phase and job (SQL v30, the API-side sums and the fake), the jobs
  decide the part, `/v1/admin/usage` adds `purpose` to the total and to each production.
- **Interface** (phase 6): shadcn `Popover` added and re-themed; `SetupCost` + `EpisodeSetupCostSlot` (episode page
  header) + `ProductionSetupCostSlot` (production overview, `DramaShell` actions); Settings → Usage "By purpose" table;
  `CLAUDE.md` rule and `docs/ARCHITECTURE.md` updated.

## Checks

- Backend: `ruff` clean on every file this plan touched (5 older E501 elsewhere); `mypy` clean (1151 files);
  `tests/test_isolation.py` green; new suites `test_cost_parts.py` (33), `test_setup_costs.py` (10); cost, usage and
  admin suites green (834 together). Full suite (run without the local `.env`, as the clean-HEAD comparison was):
  45 failed / 6,293 passed vs 44 failed at a clean HEAD worktree. The 44 are the same tests; the one extra,
  `tests/adam/test_parallel.py::test_a_continued_delivery_keeps_the_mode...` (retired Adam, a zero-second budget that
  depends on thread timing), passes alone and 3/3 with its file: a timing flake under load, not this plan.
- SQL: the newer `token_usage_totals` (now v30) applied to a throwaway Postgres 16 (v28 tables + v17 seed + v29 twice): it equals
  `group_rows` exactly with phase and job; month priced from sums vs per row: 2 micro-dollars apart (rounding).
- Interface: `tsc` clean; lint has one older warning (`script-edit-form.tsx`, unused `cn`); vitest 573/574, the one
  failure the older `raphael-panel.test.tsx`.

## The person's (phase 8)

1. Apply `Database/upgrade_v29_to_v30.sql` (only the month function changes), then deploy both. Nothing to switch on:
   rows name their scene from the first run after deploy.
2. Open an episode: "Episode setup ≈" should hold its reading, build share and Raphael; compare with the chat's
   measurement (Love Hour 4: setup ≈ $1.63 before Raphael, Raphael ≈ $1.45). Raphael runs from before the deploy have no
   scene on their rows: they appear as "Production build, shared by lines" (D6).
3. Expect every "Scene ≈" to drop (no retry margin, no setup) and the new setup figures to hold the difference.
