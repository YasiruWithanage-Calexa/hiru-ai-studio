-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v1 (Phases 0 + 1: people, roles, productions, jobs,
-- documents, RAG store, craft techniques, token usage).
--
-- HOW TO APPLY: Supabase dashboard → SQL Editor → paste this whole file → Run, on an EMPTY
-- project. It runs in one transaction: if any statement fails, nothing is created.
-- It is the same schema as supabase/migrations/20261023000000 … 20261023071230 combined
-- (verified by loading both into empty databases and comparing the dumps).
--
-- After applying, in the dashboard:
--   * Authentication → Sign In / Providers: turn OFF "Allow new users to sign up" (invite-only;
--     keep the Email provider itself ON or nobody can log in).
--   * Authentication → URL Configuration: Site URL http://localhost:3000, and add
--     http://localhost:3000/auth/accept to Redirect URLs (invite e-mails land there).
--
-- Access model (PLAN.md §9):
--   * profiles.app_role: 'admin' | 'member'. Admins see and do everything.
--   * production_members.role: what a member may do inside one production.
--   * RLS governs VISIBILITY only. There are deliberately no INSERT/UPDATE/DELETE policies for
--     browser roles: every write goes through the API (service role), which enforces the
--     permission table in contracts/roles.py. A missing write policy means "denied".
--   * The SQL editor and Table editor run as `postgres` and bypass RLS: direct edits there are
--     not permission-checked and not written to audit_log.
-- ═══════════════════════════════════════════════════════════════════════════════════════════

begin;

create extension if not exists vector with schema extensions;

-- ── types ────────────────────────────────────────────────────────────────────────────────
create type public.app_role as enum ('admin', 'member');
create type public.production_role as enum ('producer', 'director', 'writer', 'production', 'reviewer');
create type public.production_kind as enum ('drama_series', 'daily', 'special');
create type public.production_status as enum ('draft', 'ready_for_director', 'in_production', 'archived');
create type public.orientation as enum ('horizontal', 'vertical');
create type public.job_status as enum ('pending', 'running', 'waiting_input', 'done', 'failed', 'cancelled');
create type public.document_role as enum ('bible', 'script', 'canon_index', 'outline', 'notes', 'other');
create type public.document_status as enum ('uploaded', 'processing', 'ready', 'rejected', 'failed');

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ── profiles (one per auth user, created by handle_new_user) ─────────────────────────────
create table public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text not null,
  display_name text not null default '',
  app_role     public.app_role not null default 'member',
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index profiles_email_key on public.profiles (lower(email));
create trigger profiles_touch before update on public.profiles
  for each row execute function public.touch_updated_at();

-- ── productions ──────────────────────────────────────────────────────────────────────────
create table public.productions (
  id          uuid primary key default gen_random_uuid(),
  title       text not null check (char_length(title) between 1 and 200),
  kind        public.production_kind not null default 'drama_series',
  orientation public.orientation not null,
  status      public.production_status not null default 'draft',
  summary     text not null default '',
  settings    jsonb not null default '{}'::jsonb,
  created_by  uuid references public.profiles (id) on delete set null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index productions_updated_idx on public.productions (updated_at desc);
create index productions_created_by_idx on public.productions (created_by);
create trigger productions_touch before update on public.productions
  for each row execute function public.touch_updated_at();

create table public.production_members (
  production_id uuid not null references public.productions (id) on delete cascade,
  user_id       uuid not null references public.profiles (id) on delete cascade,
  role          public.production_role not null,
  added_by      uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (production_id, user_id)
);
create index production_members_user_idx on public.production_members (user_id);
create index production_members_added_by_idx on public.production_members (added_by);
create trigger production_members_touch before update on public.production_members
  for each row execute function public.touch_updated_at();

-- ── invitations ──────────────────────────────────────────────────────────────────────────
-- Sign-up is invite-only. An admin creates an invitation and the API sends Supabase's invite
-- email; when the invited user's auth row appears, handle_new_user() applies every pending
-- invitation for that email (workspace role + production roles).
create table public.invitations (
  id              uuid primary key default gen_random_uuid(),
  email           text not null check (email = lower(email)),
  app_role        public.app_role not null default 'member',
  production_id   uuid references public.productions (id) on delete cascade,
  production_role public.production_role,
  invited_by      uuid references public.profiles (id) on delete set null,
  accepted_at     timestamptz,
  created_at      timestamptz not null default now(),
  check ((production_id is null) = (production_role is null))
);
create unique index invitations_pending_key
  on public.invitations (email, coalesce(production_id, '00000000-0000-0000-0000-000000000000'::uuid))
  where accepted_at is null;
create index invitations_invited_by_idx on public.invitations (invited_by);
create index invitations_production_idx on public.invitations (production_id);

-- ── audit ────────────────────────────────────────────────────────────────────────────────
create table public.audit_log (
  id            bigint generated always as identity primary key,
  production_id uuid references public.productions (id) on delete cascade,
  actor_user_id uuid references public.profiles (id) on delete set null,
  actor_agent   text,                -- set when an agent made the change on a user's behalf
  action        text not null,       -- e.g. 'production.create', 'member.role_change'
  entity        text not null,
  entity_id     text,
  diff          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index audit_log_production_idx on public.audit_log (production_id, created_at desc);
create index audit_log_actor_idx on public.audit_log (actor_user_id);

-- ── jobs ─────────────────────────────────────────────────────────────────────────────────
create table public.jobs (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null,       -- contracts.jobs.JobKind; text so a new kind needs no schema change
  status        public.job_status not null default 'pending',
  production_id uuid references public.productions (id) on delete cascade,
  requested_by  uuid references public.profiles (id) on delete set null,
  request       jsonb not null default '{}'::jsonb,
  result        jsonb,
  error         text,
  cursor        integer not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index jobs_production_idx on public.jobs (production_id, created_at desc);
create index jobs_requested_by_idx on public.jobs (requested_by, created_at desc);
create trigger jobs_touch before update on public.jobs
  for each row execute function public.touch_updated_at();

create table public.job_events (
  seq        bigint generated always as identity primary key,
  job_id     uuid not null references public.jobs (id) on delete cascade,
  type       text not null,          -- contracts.jobs.JobEventType
  agent      text,
  payload    jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index job_events_job_idx on public.job_events (job_id, seq);

-- ── documents ────────────────────────────────────────────────────────────────────────────
create table public.documents (
  id              uuid primary key default gen_random_uuid(),
  production_id   uuid not null references public.productions (id) on delete cascade,
  filename        text not null check (char_length(filename) between 1 and 255),
  mime_type       text not null,
  size_bytes      bigint not null check (size_bytes > 0),
  sha256          text not null,
  storage_path    text not null,
  status          public.document_status not null default 'uploaded',
  detected_role   public.document_role,
  role_confidence real check (role_confidence between 0 and 1),
  role_reason     text not null default '',
  confirmed_role  public.document_role,
  confirmed_by    uuid references public.profiles (id) on delete set null,
  page_count      integer,
  char_count      integer,
  chunk_count     integer not null default 0,
  warnings        jsonb not null default '[]'::jsonb,   -- e.g. legacy (non-Unicode) Sinhala font suspected
  error           text,
  uploaded_by     uuid references public.profiles (id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (production_id, sha256)                        -- the same file twice is one document
);
create index documents_production_idx on public.documents (production_id, created_at desc);
create index documents_confirmed_by_idx on public.documents (confirmed_by);
create index documents_uploaded_by_idx on public.documents (uploaded_by);
create trigger documents_touch before update on public.documents
  for each row execute function public.touch_updated_at();

-- ── chunks: the RAG store, one table separated by corpus and scope ───────────────────────
-- Retrieval (PLAN.md §7) is HYBRID: pgvector cosine search + Postgres full-text search, fused
-- by reciprocal rank fusion in match_chunks. Both halves are absent-safe: a chunk with no
-- embedding is still found by its words, and a query with no embedding runs text-only.
-- Full text uses the 'english' configuration: English stopwords are dropped and English is
-- stemmed, while Sinhala words pass through whole (verified, including ZWJ conjuncts).
create table public.chunks (
  id             uuid primary key default gen_random_uuid(),
  corpus         text not null check (corpus in ('craft', 'production_docs', 'canon', 'memory')),
  production_id  uuid references public.productions (id) on delete cascade,
  document_id    uuid references public.documents (id) on delete cascade,
  source         text not null default '',               -- repo path for global corpora
  ord            integer not null default 0,
  heading        text not null default '',
  context_header text not null default '',
  content        text not null,
  content_hash   text not null,
  embedding      extensions.vector(1536),
  embedding_model text not null default '',
  meta           jsonb not null default '{}'::jsonb,      -- page_start, page_end, kind, specialty ...
  fts            tsvector generated always as (
                   setweight(to_tsvector('english', coalesce(heading, '') || ' ' || coalesce(context_header, '')), 'A')
                   || setweight(to_tsvector('english', content), 'B')
                 ) stored,
  created_at     timestamptz not null default now(),
  -- craft is global; every other corpus belongs to one production
  check ((corpus = 'craft') = (production_id is null))
);
create index chunks_scope_idx on public.chunks (production_id, corpus);
create index chunks_document_idx on public.chunks (document_id, ord);
create index chunks_fts_idx on public.chunks using gin (fts);
create index chunks_embedding_idx on public.chunks
  using hnsw (embedding extensions.vector_cosine_ops);
create index chunks_hash_idx on public.chunks (content_hash);

-- ── craft techniques: intent → technique (PromptMotion schema-v34, 1536-dim) ─────────────
-- `effect_text` (use case first, then definition, then the label) is what is embedded and
-- searched, because queries arrive as feelings, not as camera vocabulary.
create table public.craft_techniques (
  id              bigint generated always as identity primary key,
  domain          text not null,
  category        text not null default '',
  name            text not null,
  abbreviation    text not null default '',
  definition      text not null default '',
  use_case        text not null default '',
  example_film    text not null default '',
  effect_text     text not null,
  embedding       extensions.vector(1536),
  embedding_model text not null default '',
  source          text not null,
  row_hash        text not null,
  fts             tsvector generated always as (to_tsvector('english', effect_text)) stored,
  created_at      timestamptz not null default now(),
  unique (source, row_hash)
);
create index craft_techniques_domain_idx on public.craft_techniques (domain, category);
create index craft_techniques_fts_idx on public.craft_techniques using gin (fts);

-- ── token usage (feeds the monthly usage %; recorded from day one) ───────────────────────
create table public.token_usage (
  id            bigint generated always as identity primary key,
  production_id uuid references public.productions (id) on delete set null,
  job_id        uuid references public.jobs (id) on delete set null,
  actor_user_id uuid references public.profiles (id) on delete set null,
  phase         text not null,        -- e.g. 'doc_ingest.role', 'doc_ingest.embed', 'search.rerank'
  model         text not null,
  input_tokens  integer not null default 0,
  cached_input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  created_at    timestamptz not null default now()
);
create index token_usage_month_idx on public.token_usage (created_at);
create index token_usage_actor_idx on public.token_usage (actor_user_id);
create index token_usage_job_idx on public.token_usage (job_id);
create index token_usage_production_idx on public.token_usage (production_id);

-- ── access helpers ───────────────────────────────────────────────────────────────────────
-- SECURITY DEFINER so policies can consult membership without recursing through RLS.
-- An inactive profile has no access at all, whatever its roles say.
create or replace function public.is_admin()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.profiles p
    where p.id = auth.uid() and p.active and p.app_role = 'admin'
  );
$$;

create or replace function public.is_active_user()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (select 1 from public.profiles p where p.id = auth.uid() and p.active);
$$;

-- Not named production_role(): a function named after an enum type parses as a cast.
create or replace function public.my_production_role(target uuid)
returns public.production_role
language sql stable security definer
set search_path = ''
as $$
  select m.role
  from public.production_members m
  join public.profiles p on p.id = m.user_id
  where m.production_id = target and m.user_id = auth.uid() and p.active;
$$;

create or replace function public.can_view_production(target uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select public.is_admin() or public.my_production_role(target) is not null;
$$;

revoke all on function public.is_admin() from public, anon;
revoke all on function public.is_active_user() from public, anon;
revoke all on function public.my_production_role(uuid) from public, anon;
revoke all on function public.can_view_production(uuid) from public, anon;
grant execute on function public.is_admin() to authenticated;
grant execute on function public.is_active_user() to authenticated;
grant execute on function public.my_production_role(uuid) to authenticated;
grant execute on function public.can_view_production(uuid) to authenticated;

-- ── new user → profile + invitations ─────────────────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer
set search_path = ''
as $$
declare
  v_email text := lower(coalesce(new.email, ''));
  v_name  text := coalesce(new.raw_user_meta_data ->> 'display_name',
                           new.raw_user_meta_data ->> 'full_name',
                           split_part(v_email, '@', 1));
  v_role  public.app_role := 'member';
begin
  if exists (select 1 from public.invitations i
             where i.email = v_email and i.accepted_at is null and i.app_role = 'admin') then
    v_role := 'admin';
  end if;

  insert into public.profiles (id, email, display_name, app_role)
  values (new.id, v_email, v_name, v_role)
  on conflict (id) do nothing;

  insert into public.production_members (production_id, user_id, role, added_by)
  select i.production_id, new.id, i.production_role, i.invited_by
  from public.invitations i
  where i.email = v_email and i.accepted_at is null and i.production_id is not null
  on conflict (production_id, user_id) do nothing;

  update public.invitations set accepted_at = now()
  where email = v_email and accepted_at is null;

  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ── search ───────────────────────────────────────────────────────────────────────────────
-- An OR of the query's words, so a long natural-language question still matches passages that
-- share only some of its words (websearch_to_tsquery would AND them and usually match nothing).
create or replace function public.or_tsquery(query_text text)
returns tsquery
language sql immutable
set search_path = ''
as $$
  select case
    when coalesce(btrim(query_text), '') = '' then null
    -- The lexemes are already stemmed by to_tsvector('english'); 'simple' takes them as they
    -- are, so they are not stemmed twice (Snowball is not idempotent on every word).
    else to_tsquery('simple', (
      select string_agg(quote_literal(lexeme), ' | ')
      from unnest(tsvector_to_array(to_tsvector('english', query_text))) as lexeme))
  end;
$$;

-- Hybrid search with reciprocal rank fusion. SECURITY INVOKER: a signed-in caller gets RLS; the
-- API calls it with the service role AFTER checking the caller may view the production.
-- Scoping (corpus, production, documents) happens BEFORE ranking, so every candidate is in scope.
-- Ordering is total (score, document, position, id): equal scores always come back in one order.
create or replace function public.match_chunks(
  query_text      text,
  query_embedding extensions.vector(1536) default null,
  p_production_id uuid default null,
  p_corpora       text[] default array['production_docs'],
  p_document_ids  uuid[] default null,
  match_count     integer default 30,
  rrf_k           integer default 60
)
returns table (
  id uuid, corpus text, production_id uuid, document_id uuid, source text, ord integer,
  heading text, context_header text, content text, meta jsonb,
  score double precision, vector_rank bigint, text_rank bigint
)
language sql stable
set search_path = ''
as $$
  with scoped as (
    select c.*
    from public.chunks c
    where c.corpus = any (p_corpora)
      and (c.production_id is null or c.production_id = p_production_id)
      -- the document filter narrows production documents only; craft has no document
      and (p_document_ids is null or c.document_id is null or c.document_id = any (p_document_ids))
  ),
  q as (select public.or_tsquery(query_text) as tsq),
  vec as (
    select s.id, row_number() over (order by s.embedding operator(extensions.<=>) query_embedding, s.id) as r
    from scoped s
    where query_embedding is not null and s.embedding is not null
    order by s.embedding operator(extensions.<=>) query_embedding, s.id
    limit greatest(match_count, 1) * 2
  ),
  txt as (
    -- ties are broken by (document, position, id) so equal scores always come back in one order
    select s.id, row_number() over (order by ts_rank_cd(s.fts, q.tsq) desc, s.document_id, s.ord, s.id) as r
    from scoped s, q
    where q.tsq is not null and s.fts @@ q.tsq
    order by ts_rank_cd(s.fts, q.tsq) desc, s.document_id, s.ord, s.id
    limit greatest(match_count, 1) * 2
  ),
  fused as (
    select coalesce(v.id, t.id) as id,
           coalesce(1.0 / (rrf_k + v.r), 0) + coalesce(1.0 / (rrf_k + t.r), 0) as score,
           v.r as vector_rank, t.r as text_rank
    from vec v full outer join txt t on v.id = t.id
  )
  select c.id, c.corpus, c.production_id, c.document_id, c.source, c.ord, c.heading,
         c.context_header, c.content, c.meta, f.score::double precision, f.vector_rank, f.text_rank
  from fused f join public.chunks c on c.id = f.id
  order by f.score desc, c.document_id, c.ord, c.id
  limit greatest(match_count, 1);
$$;

-- Intent → technique. Categories are an optional hint; an unknown category degrades to the
-- whole domain, never to zero rows. Text-only when there is no embedding.
create or replace function public.match_craft_techniques(
  query_text       text,
  query_embedding  extensions.vector(1536) default null,
  match_domain     text default '',
  match_categories text[] default null,
  match_count      integer default 5,
  rrf_k            integer default 60
)
returns table (
  id bigint, domain text, category text, name text, abbreviation text, definition text,
  use_case text, example_film text, score double precision
)
language sql stable
set search_path = ''
as $$
  with filtered as (
    select t.* from public.craft_techniques t
    where (match_domain = '' or t.domain = match_domain)
      and (match_categories is null or cardinality(match_categories) = 0
           or t.category = any (match_categories)
           or not exists (select 1 from public.craft_techniques c where c.category = any (match_categories)))
  ),
  q as (select public.or_tsquery(query_text) as tsq),
  vec as (
    select f.id, row_number() over (order by f.embedding operator(extensions.<=>) query_embedding, f.id) as r
    from filtered f where query_embedding is not null and f.embedding is not null
  ),
  txt as (
    select f.id, row_number() over (order by ts_rank_cd(f.fts, q.tsq) desc, f.id) as r
    from filtered f, q where q.tsq is not null and f.fts @@ q.tsq
  ),
  fused as (
    select coalesce(v.id, t.id) as id,
           coalesce(1.0 / (rrf_k + v.r), 0) + coalesce(1.0 / (rrf_k + t.r), 0) as score
    from vec v full outer join txt t on v.id = t.id
  )
  select t.id, t.domain, t.category, t.name, t.abbreviation, t.definition, t.use_case,
         t.example_film, f.score::double precision
  from fused f join public.craft_techniques t on t.id = f.id
  order by f.score desc, t.id
  limit greatest(match_count, 1);
$$;

grant execute on function public.or_tsquery(text) to authenticated, service_role;
grant execute on function public.match_chunks(text, extensions.vector, uuid, text[], uuid[], integer, integer)
  to authenticated, service_role;
grant execute on function public.match_craft_techniques(text, extensions.vector, text, text[], integer, integer)
  to authenticated, service_role;
revoke execute on function public.match_chunks(text, extensions.vector, uuid, text[], uuid[], integer, integer) from anon;
revoke execute on function public.match_craft_techniques(text, extensions.vector, text, text[], integer, integer) from anon;

-- ── row level security (read-only for browser roles) ─────────────────────────────────────
-- Argument-free helpers and auth.uid() are wrapped in (select ...) so Postgres evaluates them
-- once per query, not once per row. can_view_production(<column>) is per-row by nature.
alter table public.profiles           enable row level security;
alter table public.productions        enable row level security;
alter table public.production_members enable row level security;
alter table public.invitations        enable row level security;
alter table public.audit_log          enable row level security;
alter table public.jobs               enable row level security;
alter table public.job_events         enable row level security;
alter table public.documents          enable row level security;
alter table public.chunks             enable row level security;
alter table public.craft_techniques   enable row level security;
alter table public.token_usage        enable row level security;

-- Staff directory: every active signed-in user may see who else is on the workspace.
create policy profiles_read on public.profiles
  for select to authenticated using ((select public.is_active_user()));

create policy productions_read on public.productions
  for select to authenticated using (public.can_view_production(id));

create policy production_members_read on public.production_members
  for select to authenticated using (public.can_view_production(production_id));

create policy invitations_read on public.invitations
  for select to authenticated using ((select public.is_admin()));

create policy audit_log_read on public.audit_log
  for select to authenticated
  using ((select public.is_admin())
         or (production_id is not null and public.can_view_production(production_id)));

create policy jobs_read on public.jobs
  for select to authenticated
  using ((select public.is_admin())
         or (production_id is not null and public.can_view_production(production_id))
         or (production_id is null and requested_by = (select auth.uid())));

create policy job_events_read on public.job_events
  for select to authenticated
  using (exists (select 1 from public.jobs j where j.id = job_id));  -- inherits jobs_read

create policy documents_read on public.documents
  for select to authenticated using (public.can_view_production(production_id));

create policy chunks_read on public.chunks
  for select to authenticated
  using ((production_id is null and (select public.is_active_user()))
         or (production_id is not null and public.can_view_production(production_id)));

create policy craft_techniques_read on public.craft_techniques
  for select to authenticated using ((select public.is_active_user()));

create policy token_usage_read on public.token_usage
  for select to authenticated using ((select public.is_admin()));

-- ── realtime ─────────────────────────────────────────────────────────────────────────────
-- The browser follows job progress and document status live (RLS applies to Realtime).
alter publication supabase_realtime add table public.jobs, public.job_events, public.documents;

-- ── storage: private bucket, service role only (files reach browsers via /files/{ticket}) ─
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 26214400,
        array['application/pdf', 'text/markdown', 'text/plain'])
on conflict (id) do nothing;

commit;
