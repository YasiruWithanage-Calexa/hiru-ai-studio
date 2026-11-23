# Setup cost apart from scene cost (plan/2026-11-23b)

Revision 1 (2026-11-23). Nothing in this plan is built. It follows plan/2026-11-23 (Usage in USD, margins), which is
built offline and uncommitted. It splits what the studio spends into three parts, each charged where it belongs:

| Part | What is in it | Charged to |
|---|---|---|
| **Production setup** | canon extraction and refine, character (face) sheets, look sheets, series identity, production memory | the production (a sheet is painted once and used by every episode) |
| **Episode setup** | reading the episode's document (`doc_ingest`, `breakdown`), script split, structure build, **all of Shot Planner Raphael** (the upload-time plan and every re-plan) | the episode |
| **Scene cost** | shot producer (design), Camera, shot prompts, first frames, video, **chat** (Zora, Sable) | the scene |

"Scene ≈ $X" shows scene cost only. A new "Episode setup ≈ $X" shows an episode's setup, upload and each re-plan as
dated entries. Settings → Usage adds a by-purpose table. The estimate's +20 % retry margin is dropped. Every phase is
offline ($0). Read this file whole, then `plan/2026-11-23/PLAN.md`, `src/api/services/costs.py`,
`src/libs/contracts/costs.py` and `src/libs/contracts/usage_totals.py`.

## 0. Rules for the chat that builds this (read before anything)

- **Final prices only, margins secret** (plan/2026-11-23 §0, unchanged). A setup entry is a final price; no field or
  label names a margin, a rate or a provider cost.
- **One set of money rules** (`contracts.costs`). Integer micro-dollars. A missing price is a note, never zero.
- **No enable switches** (the person, 2026-11-20). This plan REMOVES one (`USAGE_SCENE`).
- **No paid call.** Tests run with `OPENAI__API_KEY=` blank and fakes only.
- **Two repos.** Backend: this repo. Interface: `..\hiru-ai-studio-interface`; its `CLAUDE.md` and `AGENTS.md` bind.
- Write code with the Write or Edit tool. Read `git status` / `git diff` of a file before editing it (other plans' work is
  uncommitted, plan/2026-11-23 among it). Never stash or reset the person's tree; compare in a separate worktree.

## 1. What is wrong today

1. **Setup is in no figure.** `api/services/costs.py` shares out only `EPISODE_PHASES = ("script_split.",
   "structure_build.", "adam.", "david.", "jonathan.")` across a production's scenes. Document reading (`doc_ingest.*`,
   `breakdown.*`), canon extraction / refine and the face and look sheets appear in no scene and no other figure.
2. **Raphael's upload-time plan is in no figure.** Raphael scopes each call to its scene (`raphael_shot_planner/graph.py`
   `replace(ctx, scene_id=...)`), but a `token_usage` row carries `scene_id` only when the `USAGE_SCENE` setting is on
   (`core/settings.py`, `RunContext.usage_scene`), and it is off by default (not in `.env`). The build job names no
   scene, so the run is found by nothing.
3. **Chat reaches a scene only through its job.** Zora and Sable run inside one scene, but with `USAGE_SCENE` off their
   rows carry no `scene_id`.
4. **The scene estimate adds +20 %** on its to-finish part (`margins.yaml` `estimate.retry`). The person: drop it.

## 2. What the person decided (2026-11-23)

- D1 Re-reads count again: a document uploaded again, a canon refine, a sheet painted again is new setup spend.
- D2 No retry margin. "Scene ≈" = spent + what is left to make, both at final prices.
- D3 A Raphael re-plan is a new setup cost (the person knows before pressing it).
- D4 Chat is scene cost: Zora and Sable run per scene.
- D5 **All of Raphael is episode setup** (recommendation (a), accepted): the upload-time plan and every re-plan. Scene
  cost is only the work done inside the scene.

## 3. The design

### 3.1 Every row knows its scene (the switch goes)

`USAGE_SCENE` / `AISettings.usage_scene` / `RunContext.usage_scene` are removed: `RunContext.usage_row` always adds
`scene_id` when the run has one. The column exists since schema v17, which the hosted project has (it is on v27+). The
services that write their own rows (`director_chat`, `canon_extract`, `doc_ingest`, `script_split`, `structure_build`,
`shot_producer`, `frame_render` stores) are audited in phase 0: each row whose work is for one scene must carry it.

### 3.2 Which part a row belongs to (`contracts/cost_parts.py`, new, pure)

A closed table, by `phase` prefix (as `IMAGE_PHASES` is closed; a test scans every manifest's `phase:` and fails on one
the table does not place):

| Part | Phases |
|---|---|
| production setup | `canon_extract.`, `breakdown.canon`, `breakdown.looks`, `breakdown.series`, `canon_refine.`, the sheet paintings (below) |
| episode setup | `doc_ingest.`, `breakdown.` (the rest), `script_split.`, `structure_build.`, `raphael.`, and the retired `adam.`, `david.`, `jonathan.` |
| scene | `shot_producer.`, `camera_agent.`, `shot_prompter.`, `frame_render.` (first frames and boards), `video_render`, `zora.`, `sable.`, `director.` |

**Sheets.** Face and look sheets are painted by `frame_render` jobs (`canon.py`, `looks.py`) under the same phase as first
frames (`frame_render.image`). Their job's request says which (`reference_entity_id` / a look id); phase 0 confirms the
keys. A `frame_render.*` row whose job is a sheet job is production setup; any other is scene. (Splitting the phase
itself, `frame_render.sheet`, is cleaner but changes the meter; noted in §7.)

Phase 0 confirms each line against the code (which component writes which phase, and for what) and records the table in
`IMPLEMENTED.md` before code is written.

### 3.3 Which episode a setup row belongs to

In this order; the first that answers wins:

1. the row's `scene_id` → that scene's episode (Raphael's upload plan and re-plans, once §3.1 is in);
2. its job's `request.scene_id` → that scene's episode (a re-plan of one scene; older rows);
3. its job's `request.document_id` → the episode whose `source_document_ids` holds that document (`doc_ingest`,
   `breakdown`, a re-read); a document in several episodes is shared by their dialogue lines;
4. otherwise (the whole-production build: `structure_build`, `script_split`, a breakdown pass over every document): shared
   across the production's episodes by their dialogue lines, the rule `scene_cost` uses today for scenes.

A row that still has no episode (a production with no episodes yet) is **production setup, unassigned to an episode**, and
is shown as such: never dropped, never zero.

### 3.4 Episode setup entries

An episode's setup is a list of dated entries, so a re-plan shows as its own cost (D1, D3):

- **Upload**: everything for the episode before its first scene was planned (reading, breakdown, build share, Raphael's
  first plan).
- **Re-plan** (one per `plan_scene_raphael` / `cinematic_scene_raphael` job a person started): its rows, labelled
  "Re-plan, scene 4" or "More cinematic, scene 4".
- **Re-read** (one per `doc_ingest` job after the first for the same document): "Document read again".

Each entry: `{label, at, total_micros, complete}`. The total is their sum. No entry has lines, rates or margins.

### 3.5 Scene ≈ $X (changed)

`api/services/costs.py::scene_cost`:
- spent = the scene's rows whose part is **scene** (§3.2) + its renders. `raphael.*`, `breakdown.*` and every other
  setup phase are left out even when they carry the scene's id;
- the episode share (`EPISODE_PHASES`, `unassigned_usage`, `lines_by_scene`) is **removed** from the scene figure: that
  work is episode setup now;
- to finish: unchanged (next video, a frame, a prompt);
- **no retry margin**: `scene_total` returns spent + to finish. `with_retry`, `margins.yaml` `estimate:` and
  `Margins.retry_bp` go; a file that still has `estimate:` is refused with a clear message (so an old copy cannot slip
  through silently).

### 3.6 The figures and where they show

| Figure | API | Who | Where in the interface |
|---|---|---|---|
| Scene ≈ $X | `GET .../scenes/{id}/cost` (unchanged shape) | `VIEW_COSTS` | as today |
| Episode setup ≈ $X | `GET /v1/productions/{pid}/episodes/{eid}/setup-cost` → `{currency, total_micros, complete, entries: [{label, at, total_micros}]}` | `VIEW_COSTS` | the episode page header, beside the episode title; a small popover lists the entries |
| Production setup ≈ $X | `GET /v1/productions/{pid}/setup-cost` → same shape (entries: "Canon", "Face sheets", "Look sheets", "Canon refine", "Not yet in an episode") | `VIEW_COSTS` | the production overview |
| Usage by purpose | `GET /v1/admin/usage` gains per production `production_setup_micros`, `episode_setup_micros`, `scene_micros` (their sum = `total_micros`) | admin | Settings → Usage: a second table "By purpose" under "By production" |

The interface `CLAUDE.md` rule ("ONE figure per scene … no popover") changes: the episode and production setup figures
are added as exceptions, and the setup popover lists dated entries (labels and final totals only).

### 3.7 Cost of the month vs the figures

Settings → Usage totals stay what they are (a month, by kind). The by-purpose table splits the same month's total into
the three parts, so the two tables add up to the same number. Setup and scene figures on the production pages are
**all-time** (an episode's setup does not reset each month).

## 4. Changes, file by file

**contracts**: `cost_parts.py` (new: the part table, `part_of(phase, job)`, `episode_of(row, job, scenes, episodes,
lines)`); `costs.py` (retry gone; `scene_total` without it; `parse_margins` refuses `estimate:`); `usage_totals.py`
(the by-purpose split; the RPC's groups gain `part` and need the job: see repo).

**core**: `core/settings.py`, `core/context.py`, `adapters/supabase_rest.py` (`usage_scene` removed); the service stores
found in phase 0.

**api**: `services/costs.py` (scene part only, no share, no retry); `services/setup_costs.py` (new: episode and
production setup, entries); `routers/costs.py` (the two setup routes); `services/usage_totals.py` + `routers/admin_usage.py`
(by purpose); repositories: rows of a production with their job's `kind` and `request` (one read), episodes with
`source_document_ids`, scenes with `episode_id`.

**schema**: none expected (all links exist: `token_usage.scene_id`, `job_id`; `jobs.request`; `episodes.source_document_ids`;
`scenes.episode_id`). If the Usage RPC must split by part in SQL, `token_usage_totals` gains a `job_kind` group column in
v30 (built: the person had applied v29, so v29 stays as applied and `upgrade_v29_to_v30.sql` re-makes the function).

**margins file**: `src/api/margins.yaml` loses `estimate:`.

**interface**: `features/production` (episode and production setup figures, popover), `features/usage-report`
(by-purpose table), `CLAUDE.md`, `docs/ARCHITECTURE.md`.

## 5. Phases

| # | What | Done when |
|---|---|---|
| 0 | Read-only audit: every writer of `token_usage` (graph context + each service store), its phases, whether it carries `scene_id`, what its job's request holds (`scene_id`, `document_id`, sheet keys); confirm the §3.2 table and §3.3 links; write both into `IMPLEMENTED.md` | table and links written down, no open phase |
| 1 | Remove `USAGE_SCENE` (§3.1) and make every scene-scoped writer carry `scene_id`. Tests: a Raphael run writes each call with its scene; a Zora / Sable turn writes its scene; no setting is read | tests green |
| 2 | `contracts/cost_parts.py`: tests: every manifest phase is placed; sheet vs first-frame by job; episode by scene, by job scene, by document, shared by lines; a document in two episodes; no episode → production setup | tests green, `mypy` clean |
| 3 | Scene ≈ without setup and without retry (§3.5): `tests/api/test_costs.py` rewritten for it: Raphael rows tagged with the scene do NOT count; chat does; no episode share; to-finish has no ×1.2; `margins.yaml` with `estimate:` is refused | tests green |
| 4 | Setup figures (§3.4, §3.6): episode and production routes; entries for upload, re-plan, re-read; `VIEW_COSTS` only; no field names a rate or margin (the secrecy scan of plan/2026-11-23 covers the new routes) | tests green |
| 5 | Usage by purpose: the three parts add up to the month's total; same answer with and without the RPC | tests green |
| 6 | Interface: episode setup figure + popover, production setup figure, Usage "By purpose" table; tests; `CLAUDE.md` rule updated | `npx next typegen && npm run check && npm run format:check` |
| 7 | Docs: backend `CLAUDE.md` (scene cost / setup paragraphs), `IMPLEMENTED.md` | read through |
| 8 | **The person's**: deploy; open an episode and check its setup against the chat's measured figures (Love Hour 4 setup ≈ $1.63 before Raphael; Raphael ≈ $1.45 on top) | the person's yes |

Before finishing each backend phase: `ruff check src tests scripts`, `mypy`, `pytest -q`.

## 6. Decisions

- D1-D5 decided (§2).
- **D6 (open)**: rows written before §3.1 (no `scene_id`, Raphael's earlier upload runs) cannot name their scene. They go
  to the episode by their job (step 3.3-2/3) or, failing that, shared by lines. Recommended: accept that for history; no
  backfill.
- **D7 (open)**: show the setup figures to `VIEW_COSTS` holders (producer, director, admin), like Scene ≈. Recommended:
  yes.
- **D8 (open)**: a split of `frame_render.image` into `frame_render.sheet` for sheets (cleaner, needs the sheet painters to
  pass a phase). Recommended: later; the job tells them apart today.

## 7. Not in this plan

- Charging setup into a per-minute price for customers (the chat's per-minute table): this plan measures; pricing
  products from it is the person's.
- Reconciling with the provider bills (plan/2026-11-23 §8).
- A monthly view of setup per episode (the setup figures are all-time).
