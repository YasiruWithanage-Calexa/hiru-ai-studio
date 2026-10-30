# Database

The hosted Supabase project `dwivfkavmtjzhypqswze` is **the one dev database**: the API, the
functions, the frontend and the scripts all use it. It is managed by hand through the
dashboard's SQL Editor and Table Editor, using the files in this folder. It runs **schema v3**
(v1 → v2 and v2 → v3 both on 2026-10-24); `upgrade_v3_to_v4.sql` (Phase 5) is ready and not run yet. The local Supabase stack is only a throwaway database for the
automated tests.

| File | What it is |
|---|---|
| `schema_v8.sql` | **The newest schema** (everything in v7 plus `scene_looks`: the look of a character a scene uses), whole. Run it once on an empty project. |
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
3. Load the 576 techniques: `python scripts/ingest_knowledge.py` (needs `OPENAI__API_KEY` for
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
   published keys. Then run `python scripts/ingest_knowledge.py` to load the craft knowledge.

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
