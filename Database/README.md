# Database

The hosted dev database is Supabase project `dwivfkavmtjzhypqswze`. It is managed by hand
through the dashboard's SQL Editor and Table Editor, using the files in this folder.

| File | What it is |
|---|---|
| `schema_v1.sql` | The whole schema (Phases 0 and 1). Run it once on an empty project. |

`schema_v1.sql` is the same schema as `supabase/migrations/` combined. This was checked by
loading each into an empty database: the dumps match, and the 49 database tests and Supabase's
advisor check pass on both. The local stack (`npx supabase start`) still builds from
`supabase/migrations/`, and the tests run there.

## First-time setup (hosted project)

1. **SQL Editor:** paste `schema_v1.sql` and run it. It runs as one transaction, so if
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
- **Structure** (tables, columns, functions, policies): put the SQL in a new numbered file,
  `changes/001_<what>.sql`, run it in the SQL Editor, and add the same change as a migration
  (`npx supabase migration new <what>`) so local tests cover it. When the changes pile up,
  they get folded into the next full schema, `schema_v2.sql`.
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
