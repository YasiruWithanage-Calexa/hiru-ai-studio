# A scene's production cost: what is built (plan/2026-11-06d)

Status 2026-11-07: **phases 1 to 5 built offline (backend and interface); phase 0 (real prices and a real bill), applying
schema v17 and the live look on localhost are the person's.** No model or provider was called, nothing was applied to the
hosted database, nothing is committed.

## Read this first

1. **The seeded prices are provisional.** `contracts/costs.py` `SEED_PRICES` (also what `upgrade_v16_to_v17.sql` seeds) are
   list prices I found on third-party sites and in the lab's own files, marked "confirm" in each row's `note`. They are
   NOT a bill. In particular: Veo 3.1 $0.40/s, Veo 3.1 Fast $0.10/$0.12 per second, `gpt-image-2` $8 / $2 / $30 per
   million tokens (image input / cached / output), `gpt-5.5` and `gpt-6.1-sol` from `lab/cinematic`. **Omni Flash is
   seeded at 720p only ($0.10/s, derived from the preview's token rate); Omni at 360p and 1080p has no price on purpose**,
   so a scene using them says "some prices are missing" until an admin adds them (`/prices`, or Phase 0).
2. **Docker was not running here**, so the migration and `017_costs.test.sql` were written but NOT run
   (`npx supabase db reset && npx supabase test db`), and the three-way dump comparison was not done. Run them before
   applying `Database/upgrade_v16_to_v17.sql`.
3. **Until v17 is applied** the API still answers: it uses the prices in code, and a scene's rows are found through the job
   that named the scene. After v17, set `USAGE_SCENE=true` so the graph engine's rows (the director chat, Zora) name their
   scene too.
4. **The schema is a v17 pair, not a fold into v14**: v14 was already applied (2026-11-07), and v15/v16 exist.

## What is built

### Phase 1 – contracts (`src/libs/contracts/costs.py`, `tests/contracts/test_costs.py`)
Money is integer micro-dollars. `Price` (tokens / video_second / estimate), `price_for` (a dated price; for tokens the
longest model prefix **that is the name or a dated snapshot of it**), `with_margin` (text 0, image 500 bp, video 1000 bp,
half up), `with_retry` (2000 bp), `kind_of(phase)` (closed list `IMAGE_PHASES`; `video_render.*` rows are only meters),
`cost_tokens`, `cost_render`, `estimate_shot_video` (takes `video_gen.resolve`'s output), `estimate_unit`,
`scene_total` (kind margins first, then retry on the to-finish sum, once). `Permission.VIEW_COSTS` for producer, director
(and admin, who holds every permission). `scripts/adam_cost.py` and `scripts/david_spike.py` now take their prices from
`SEED_PRICES`, and still report actual cost with no margin.

### Phase 2 – storage (`Database/schema_v17.sql`, `upgrade_v16_to_v17.sql`, `supabase/migrations/20261107102641_costs.sql`)
`prices` (RLS on, admin read only, no write policy; seeded only into an empty table), `token_usage.scene_id` (FK on delete
set null, index `(scene_id, created_at)`), and a backfill from `jobs.request->>'scene_id'`. `supabase/tests/database/
017_costs.test.sql` covers RLS, the constraints and the scene index.

### Phase 3 – writers
`RunContext.usage_scene` (setting `USAGE_SCENE`, off by default like `USAGE_DETAIL`) adds `scene_id` to a run's rows; the
legacy director chat does the same from its payload. `video_render` records `seconds_rendered` and `takes_made` in
`video_renders.usage`.

### Phase 4 – API (`routers/costs.py`, `services/costs.py`, `repositories` `CostsRepo`)
`GET /v1/productions/{pid}/scenes/{sid}/cost` → `{currency, total_micros, designed, complete}` and nothing else (404 for an
unseen production, 403 without `VIEW_COSTS`). `GET|PUT /v1/prices` (admin; a new row only, never in the past, audited as
`prices.add`). `tests/api/test_costs.py` (44 tests, with `tests/contracts/test_costs.py`).

### Phase 5 – interface (`hiru-ai-studio-interface`)
`features/production/components/scene-cost.tsx` ("Scene ≈ $20.86", title text in words only) beside the batch buttons,
drawn only for people with `view_costs`; `features/prices` and `/prices` (admin list and "add a price from now on"), linked
from the account area for admins.

## Deviations from the plan (each is easy to turn back)

- **`unit_micros` column on `prices`** for the `estimate` kind (a flat price of one frame or one prompt). The plan's column
  list had no place for it.
- **Rows without a `scene_id` are attributed through their job** at read time (`jobs.request->>'scene_id'`), not only by the
  backfill, so the legacy engines count without touching their six handlers. The API's `UsageContext` (search and embedding
  rows) was left alone: those rows are cents and name no scene.
- **Reasoning tokens are not added a second time.** A row's `output_tokens` is the provider's completion count, which
  already includes them (`adam_cost.py` says so too).
- **"Prompts: unlocked shots"** is read as every shot WITHOUT a current prompt (not only unlocked ones), the same way frames
  are counted for every shot without a current accepted frame; a shot with an accepted take is finished and adds nothing.
  A shot that carries on from the previous take needs no frame.
- **The episode share (D-A)** pools the production's unassigned `script_split.`, `structure_build.`, `adam.`, `david.` and
  `jonathan.` rows (no scene, from no single-scene job) and gives each scene its share of the production's dialogue lines.
- **Price history for frames and prompts** (median of this production's last 20 jobs; else across productions; else the
  seeded `estimate`) is read from `token_usage`: a frame is a `frame_render.*` job's cost over its pictures, a prompt is a
  `shot_producer.craft` call.
- **No mock in the interface seam**: the app reads the live API (there is no cost mock to keep in step), so the tests build
  the figure from the API's shape.

## Open (the person's)

- **Phase 0**: confirm the prices above; run `scripts/video_probe.py --generate --yes` once to check "seconds x price" and
  whether failed or refused renders are billed (D-C). Until then `usage.billed` is never set, so only `done` renders count.
- Run the local DB checks (item 2), apply `upgrade_v16_to_v17.sql`, set `USAGE_SCENE=true`, restart the API and functions.
- Look at a real scene on localhost (it reads real usage), and decide D-A, D-B, D-C, D-D (§11) or keep the proposals.
- Not built, on purpose (§9): a production or episode total, any budget or alert, margins on text calls, a breakdown.
