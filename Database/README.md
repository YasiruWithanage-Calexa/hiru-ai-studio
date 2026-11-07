# Database

The hosted Supabase project `dwivfkavmtjzhypqswze` is **the one dev database**: the API, the
functions, the frontend and the scripts all use it. It is managed by hand through the
dashboard's SQL Editor and Table Editor, using the files in this folder. It runs **schema v3**
(v1 → v2 and v2 → v3 both on 2026-10-24); `upgrade_v3_to_v4.sql` (Phase 5) is ready and not run yet. The local Supabase stack is only a throwaway database for the
automated tests.

| File | What it is |
|---|---|
| `schema_v16.sql` | **The newest schema** (everything in v15 plus the document reader, plan/2026-11-06f: `documents.reading_path` / `read_from` and `scenes.read_from` / `read_confirmed_by` / `read_confirmed_at`), whole. Run it once on an empty project. |
| `upgrade_v15_to_v16.sql` | Moves a project on v15 to v16 (two columns on `documents`, three and an index on `scenes`). Run once, only on such a project, before `READER__ENABLED=true`. Safe to re-run. |
| `schema_v15.sql` | Kept for reference (the previous schema) (everything in v14 plus draft and final first frames: `first_frames.stage` and `first_frames.draft_id`, one accepted frame per shot AND stage), whole. Run it once on an empty project. |
| `upgrade_v14_to_v15.sql` | Moves a project on v14 to v15 (two columns, a constraint and two indexes on `first_frames`). Run once, only on such a project. Until it is run, no first frame can be asked for. **Not run yet: applying it is a person's decision.** |
| `schema_v14.sql` | Kept for reference (everything in v13 plus in-app video generation, plan/2026-11-06c: the `video_renders` table, `takes.origin`, `takes.render_id` and `shots.video_settings`; and Zora's undo history, plan/2026-11-06e: the `scene_plan_revisions` table), whole. Run it once on an empty project. |
| `upgrade_v13_to_v14.sql` | Moves a project on v13 to v14 (the `video_renders` table and three columns for it, and the `scene_plan_revisions` table: without it Zora runs with no undo). Run once, only on such a project. Then set `GOOGLE__API_KEY` for the `video_render` function. Applied by the person (2026-11-07). |
| `schema_v13.sql` | Kept for reference (everything in v12 plus `scenes.jonathan` and `'jonathan'` as a planner a shot may name: Shot Planner Jonathan, plan/2026-11-06b), whole. Run it once on an empty project. |
| `upgrade_v12_to_v13.sql` | Moves a project on v12 to v13 (one column on `scenes` and the planner check on `shots`). Run once, only on such a project. **Not run yet: applying it is a person's decision.** |
| `schema_v12.sql` | Kept for reference (everything in v11 plus `token_usage.reasoning_tokens`: how much of a call's output was hidden reasoning, plan/2026-11-05; the `production_memory` table, what the documents say about how to make the drama, plan/2026-11-05d; and `scenes.david` with `'david'` as a planner a shot may name: Shot Planner David, plan/2026-11-05e), whole. Run it once on an empty project. |
| `upgrade_v11_to_v12.sql` | Moves a project on v11 to v12 (one column on `token_usage`, the `production_memory` table, `scenes.david` and the planner check on `shots`). Run once, only on such a project. Then set `USAGE_DETAIL=true` and restart. |
| `schema_v11.sql` | Kept for reference (everything in v10 plus `shots.card`, `shots.planner` and `scenes.adam`: Shot Planner Adam, plan/2026-11-04b), whole. Run it once on an empty project. |
| `upgrade_v10_to_v11.sql` | Moves a project on v10 to v11 (two columns on `shots`, one on `scenes`). Run once, only on such a project. |
| `schema_v10.sql` | Kept for reference (everything in v9 plus the per-component columns of `token_usage`: `component`, `component_version`, `prompt_hash`, `tool_calls`, `tool_result_tokens`; plan/2026-11-04), whole. Run it once on an empty project. |
| `upgrade_v9_to_v10.sql` | Moves a project on v9 to v10 (five columns and one index on `token_usage`). Run once, only on such a project. |
| `schema_v9.sql` | Everything in v8 plus `shots.intent`, `scenes.coverage`, `scenes.reading` and `scenes.staging` (plan/2026-11-01d), `first_frames.checks`, the `pending_actions` table and `dialogue_lines.source_text` / `source_lang`: plan/2026-11-01 and 2026-11-01c), whole. Run it once on an empty project. |
| `upgrade_v8_to_v9.sql` | Moves a project on v8 to v9 (four JSON columns, the `pending_actions` table and the two source columns on `dialogue_lines`). Run once, only on such a project. |
| `schema_v8.sql` | Everything in v7 plus `scene_looks` (the look of a character a scene uses), kept for reference. |
| `upgrade_v7_to_v8.sql` | Moves a project on v7 to v8 (the `scene_looks` table). Run once, only on such a project. |
| `schema_v7.sql` | Everything in v6 plus `canon_looks` (what a character wears per stretch of episodes), kept for reference. |
| `upgrade_v6_to_v7.sql` | Moves a project on v6 to v7 (the `canon_looks` table). Run once, only on such a project. |
| `schema_v6.sql` | The Phase 0–5 schema with `shots.person_edits` and the cinematography columns on `craft_techniques`, kept for reference. |
| `upgrade_v5_to_v6.sql` | Moves a project on v5 to v6 (the technique library takes the 629-term cinematography database). Run once, only on such a project. |
| `schema_v5.sql` | The Phase 0–5 schema with `shots.person_edits`, kept for reference. |
| `upgrade_v4_to_v5.sql` | Moves a project on v4 to v5 (`shots.person_edits`: the marks a person sets on a shot in the director chat). Run once, only on such a project. |
| `schema_v4.sql` | The Phase 0–5 schema, kept for reference. |
| `upgrade_v3_to_v4.sql` | Moves a project on v3 to v4 (takes, usage budget, `takes` bucket). Run once, only on such a project. |
| `schema_v3.sql` | The Phase 0–4 schema, kept for reference. |
| `upgrade_v2_to_v3.sql` | Moves a project on v2 to v3 (the Production panel). Run once, only on such a project. |
| `schema_v2.sql` | The Phase 0–3 schema, kept for reference. |
| `upgrade_v1_to_v2.sql` | Moves a project that already has v1 to v2. Run once, only on such a project. |
| `schema_v1.sql` | The Phase 0–1 schema, kept for projects still on it. |

Each `schema_vN.sql` is the whole schema at that version: the same schema as
`supabase/migrations/` up to that point, combined. For v2 this was checked by loading it into an
empty database and comparing the dump with the one the migrations build (identical), and by
running the 94 database tests and Supabase's advisor check on it (all pass). v1 plus
`upgrade_v1_to_v2.sql` gives the identical dump too. The local stack (`npx supabase start`)
still builds from `supabase/migrations/`, and the tests run there.

## v15 (not yet verified)

`schema_v15.sql` and `upgrade_v14_to_v15.sql` carry `first_frames.stage`, `first_frames.draft_id`, the constraint
`first_frames_draft_final` and the indexes `first_frames_one_accepted` (now on `shot_id, stage`) and `first_frames_draft_idx`
(`supabase/migrations/20261107022920_frame_stage.sql`), with five new assertions in
`supabase/tests/database/005_production.test.sql`. The three-way dump comparison (migrations, v15 on an empty database, v14 +
upgrade), `supabase test db` and the advisors still have to be run on the local stack (Docker was not running).

## v14 check (2026-11-07)

The `public,storage` dumps of the migrations, of `schema_v14.sql` on an empty database and of `schema_v13.sql` +
`upgrade_v13_to_v14.sql` were compared on the local stack: v14 and v13 + upgrade are identical to each other, and
`video_renders` and `scene_plan_revisions` are identical in all three. Both differ from the migrations in two older
things this version did not touch: the column order of `dialogue_lines` (`source_text`, `source_lang`) and of
`token_usage` (`created_at`), and the comment on `token_usage.reasoning_tokens`, which the hand-made files lack. The 17
database test files (214 tests) and the advisors (no issues) pass on the migrations.

## Moving a project from v10 to v11

1. **SQL Editor:** paste `upgrade_v10_to_v11.sql` and run it, once. It runs as one transaction and can be re-run.
2. Check: `select card, planner from public.shots limit 1;` runs (old rows show `{}` and `classic`), and
   `select adam from public.scenes limit 1;` shows `{}`.
3. Restart the API and the functions. Until it is applied, a production set to Adam (`settings.shot_planner`) cannot write
   its shots; the classic planner does not touch the new columns, so nothing else changes.

v11 was **not** verified with a dump comparison or the database tests (no Docker on the machine it was written on):
run `npx supabase db reset` and `npx supabase test db` (`011_adam.test.sql`) where Docker is available.

## Moving a project from v9 to v10

1. **SQL Editor:** paste `upgrade_v9_to_v10.sql` and run it, once. It runs as one transaction and can be re-run.
2. Check: `select component, tool_calls from public.token_usage limit 1;` runs (the columns exist; old rows show `''` and `0`).
3. Set `USAGE_DETAIL=true` where the API and the functions run, and restart them. Until then a model call's row is written
   without the new columns, so nothing breaks if the upgrade comes later than the code.

v10 was **not** verified with a dump comparison (see the test list in `plan/2026-11-04/IMPLEMENTED.md`).

## Moving a project from v8 to v9

1. **SQL Editor:** paste `upgrade_v8_to_v9.sql` and run it, once. It runs as one transaction.
2. Check: `select intent from public.shots limit 1;` returns `{}` (or no rows), and `select count(*) from public.pending_actions;` returns 0. (If v9 was already run before 2026-11-01c, run only the `pending_actions` part of `upgrade_v8_to_v9.sql`; until then the director chat answers every "i confirm" with "There is nothing waiting to apply." Likewise for the two `source_*` columns on `dialogue_lines`: run only that `alter table`; until then a translation can be shown but not applied, because saving the line fails on the unknown column.)
3. Restart the API and the `shot_producer` and `frame_render` functions (they read and write the
   new columns). Until it is applied, writing an intent or a frame's checks fails.

If v9 was already run before plan/2026-11-01d, run only `alter table public.scenes add column if not exists reading jsonb not null default '{}'::jsonb;` from `upgrade_v8_to_v9.sql`; until then the split cannot write a scene's reading (the scene's shots are not written either, because the same update carries it) and the reading endpoints fail on the unknown column. Restart the API and the `script_split`, `director_chat`, `shot_producer` and `frame_render` functions.

If v9 was already run before the staging map (plan/2026-11-01d, Phase 4), run only `alter table public.scenes add column if not exists staging jsonb not null default '{}'::jsonb;` from `upgrade_v8_to_v9.sql`; until then the split's scene update fails on the unknown column. Restart the API and the `script_split` function.

v9 was **not** verified with a dump comparison or the database tests (no Docker).

## Moving a project from v7 to v8

1. **SQL Editor:** paste `upgrade_v7_to_v8.sql` and run it, once. It runs as one transaction.
2. Check: `select count(*) from public.scene_looks;` returns 0.
3. Restart the API (it reads and writes the table).

v8 was **not** verified with a dump comparison or the database tests (no Docker).

## Moving a project from v6 to v7

1. **SQL Editor:** paste `upgrade_v6_to_v7.sql` and run it, once. It runs as one transaction.
2. Check: `select count(*) from public.canon_looks;` returns 0.
3. Restart the API and the `frame_render` function (they read and write the table).

v7 was **not** verified with a dump comparison or the database tests (no Docker). The tests are in
`supabase/tests/database/007_looks.test.sql`; run them with `npx supabase test db` where Docker is available.

## Moving a project from v5 to v6

1. **SQL Editor:** paste `upgrade_v5_to_v6.sql` and run it, once. It runs as one transaction.
2. Check: `select slug, prompt_phrase, ai_supported from public.craft_techniques limit 1;` runs.
3. Load the 576 techniques: `hiru-ai ingest --all` (needs `OPENAI__API_KEY` for
   embeddings; without it, search is keyword-only), then `python scripts/eval_retrieval.py --runs 3`.
4. Restart the API and the `shot_producer` function (they read the technique search).

v6 was **not** verified with a dump comparison or the database tests (no Docker).

## Moving a project from v4 to v5

1. **SQL Editor:** paste `upgrade_v4_to_v5.sql` and run it, once. It runs as one transaction.
2. Check: `select person_edits from public.shots limit 1;` returns `{}`.
3. Restart the API and the `director_chat`, `shot_producer` and `frame_render` functions: they
   write and read the new column. v5 was **not** verified with a dump comparison (no Docker).

## Moving a project from v3 to v4

1. **SQL Editor:** paste `upgrade_v3_to_v4.sql` and run it, once. It runs as one transaction.
2. Check: `select id from storage.buckets order by id;` now also lists `takes`.
3. Optional: set the monthly budget with `PUT /v1/usage/budget` (admin); until then the API uses
   `USAGE__MONTHLY_TOKEN_BUDGET`.

v4 was checked like v3: identical dumps from the migrations, from v4 alone and from v3 + this
upgrade, and the 126 database tests pass on each.

## Moving a project from v2 to v3

1. **SQL Editor:** paste `upgrade_v2_to_v3.sql` and run it, once. It runs as one transaction.
2. Check: `select id from storage.buckets order by id;` lists `documents`, `frames`, `references`.
3. Nothing to re-run: existing shots start with no design and the recommended camera.

v3 was checked like v2: the dump of a database built from the migrations, of v3 loaded into an
empty one, and of v2 + this upgrade are identical (buckets, Realtime tables, personas and the
`graph` schema too), and the 113 database tests and the advisors pass on each.

## Moving a project from v1 to v2

1. **SQL Editor:** paste `upgrade_v1_to_v2.sql` and run it, once. It runs as one transaction.
2. Check: `select count(*) from public.director_personas;` returns 5.
3. Re-read the documents uploaded before the upgrade ("Re-read" on each, or
   `POST .../documents/{id}/reingest`): the structure build needs their extracted text, which v1
   did not keep.
4. For the functions, set `SUPABASE__DB_URL` (Settings → Database → session pooler string),
   `API__INTERNAL_URL` and `API__INTERNAL_SECRET` in `.env`.

## First-time setup (hosted project)

1. **SQL Editor:** paste `schema_v7.sql` and run it. It runs as one transaction, so if
   anything fails, nothing is created.
2. **Authentication → Sign In / Providers:** turn **off** "Allow new users to sign up". Keep
   the Email provider **on**, or nobody can log in.
3. **Authentication → URL Configuration:** set Site URL to `http://localhost:3000` and add
   `http://localhost:3000/auth/accept` to Redirect URLs.
4. **First admin:** go to Authentication → Users → Add user (auto-confirm). The trigger creates
   their profile as `member`. Then run:
   ```sql
   update public.profiles set app_role = 'admin' where email = 'yasiru@calexa.io';
   ```
5. **Point the backend at it:** in `.env`, set `SUPABASE__URL=https://dwivfkavmtjzhypqswze.supabase.co`
   and `SUPABASE__SERVICE_ROLE_KEY=<the secret key from Settings → API Keys>`. Leave
   `SUPABASE__JWT_SECRET` empty: hosted sign-in tokens are checked against the project's
   published keys. Then run `hiru-ai ingest --all` to load the craft knowledge.

## Changing things

- **Data:** edit it directly in the Table Editor or SQL Editor. Note that these run as
  `postgres`: they skip row-level security and the API's permission checks, and write nothing
  to `audit_log`.
- **Structure** (tables, columns, functions, policies): the change is made as a migration
  (`npx supabase migration new <what>`) so local tests cover it, and the schema moves to the
  next version: a new whole `schema_vN.sql`, plus `upgrade_v(N-1)_to_vN.sql` for the project
  that already runs the previous version. Changes made while a version is being worked on go
  into the same pair, so there is one file to run per version, not a pile of small ones.
- If you change structure straight in the dashboard, say so, so the files and migrations can
  be brought back in line. Code that reads a column which only exists in the hosted database
  breaks everywhere else.

## Useful queries

```sql
-- who has which workspace role
select email, app_role, active from public.profiles order by email;

-- give someone a role in a production
insert into public.production_members (production_id, user_id, role)
select '<production uuid>', id, 'director' from public.profiles where email = 'someone@hirutv.lk'
on conflict (production_id, user_id) do update set role = excluded.role;

-- documents that failed or were rejected, and why
select filename, status, error, warnings from public.documents where status in ('failed', 'rejected');

-- model token use this month, by phase
select phase, model, sum(input_tokens) as input, sum(cached_input_tokens) as cached, sum(output_tokens) as output
from public.token_usage where created_at >= date_trunc('month', now()) group by 1, 2 order by 3 desc;
```
