# Database

The hosted Supabase project `dwivfkavmtjzhypqswze` is **the one dev database**: the API, the
functions, the frontend and the scripts all use it. It is managed by hand through the
dashboard's SQL Editor and Table Editor, using the files in this folder. It runs **schema v2**
(upgraded from v1 on 2026-10-24). The local Supabase stack is only a throwaway database for the
automated tests.

| File | What it is |
|---|---|
| `schema_v2.sql` | **The current schema** (Phases 0–3), whole. Run it once on an empty project. |
| `upgrade_v1_to_v2.sql` | Moves a project that already has v1 to v2. Run once, only on such a project. |
| `schema_v1.sql` | The Phase 0–1 schema, kept for projects still on it. |

Each `schema_vN.sql` is the whole schema at that version: the same schema as
`supabase/migrations/` up to that point, combined. For v2 this was checked by loading it into an
empty database and comparing the dump with the one the migrations build (identical), and by
running the 94 database tests and Supabase's advisor check on it (all pass). v1 plus
`upgrade_v1_to_v2.sql` gives the identical dump too. The local stack (`npx supabase start`)
still builds from `supabase/migrations/`, and the tests run there.

## Moving a project from v1 to v2

1. **SQL Editor:** paste `upgrade_v1_to_v2.sql` and run it, once. It runs as one transaction.
2. Check: `select count(*) from public.director_personas;` returns 5.
3. Re-read the documents uploaded before the upgrade ("Re-read" on each, or
   `POST .../documents/{id}/reingest`): the structure build needs their extracted text, which v1
   did not keep.
4. For the functions, set `SUPABASE__DB_URL` (Settings → Database → session pooler string),
   `API__INTERNAL_URL` and `API__INTERNAL_SECRET` in `.env`.

## First-time setup (hosted project)

1. **SQL Editor:** paste `schema_v2.sql` and run it. It runs as one transaction, so if
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
