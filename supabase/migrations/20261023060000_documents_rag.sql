-- Phase 1: documents, the RAG store, craft techniques, token usage.
--
-- Retrieval (PLAN.md §7) is HYBRID: pgvector cosine search + Postgres full-text search, fused
-- by reciprocal rank fusion in `match_chunks`. Both halves are absent-safe: a chunk with no
-- embedding (no OpenAI key yet, or embedding failed) is still found by its words, and a query
-- with no embedding runs text-only. Full text uses the 'english' configuration: English
-- stopwords are dropped (with 'simple', "the" matched every passage) and English is stemmed,
-- while Sinhala words pass through whole and unchanged (verified, including ZWJ conjuncts).

create extension if not exists vector with schema extensions;

-- ── documents ────────────────────────────────────────────────────────────────────────────
create type public.document_role as enum ('bible', 'script', 'canon_index', 'outline', 'notes', 'other');
create type public.document_status as enum ('uploaded', 'processing', 'ready', 'rejected', 'failed');

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
create trigger documents_touch before update on public.documents
  for each row execute function public.touch_updated_at();

-- ── chunks: one table, separated by corpus and scope ─────────────────────────────────────
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
-- Structured rows, every CSV column verbatim. `effect_text` (use case first, then definition,
-- then the label) is what is embedded and searched, because queries arrive as feelings
-- ("the viewer must feel she is powerless"), not as camera vocabulary.
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

-- ── token usage (feeds the monthly usage % from Phase 5; recorded from day one) ──────────
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
-- Production corpora are small enough that an exact scan beats the HNSW index's approximation.
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
-- whole domain, never to zero rows (PromptMotion's rule). Text-only when there is no embedding.
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

-- ── RLS (read-only for browser roles, as in the foundation migration) ────────────────────
alter table public.documents        enable row level security;
alter table public.chunks           enable row level security;
alter table public.craft_techniques enable row level security;
alter table public.token_usage      enable row level security;

create policy documents_read on public.documents
  for select to authenticated using (public.can_view_production(production_id));

create policy chunks_read on public.chunks
  for select to authenticated
  using ((production_id is null and public.is_active_user())
         or (production_id is not null and public.can_view_production(production_id)));

create policy craft_techniques_read on public.craft_techniques
  for select to authenticated using (public.is_active_user());

create policy token_usage_read on public.token_usage
  for select to authenticated using (public.is_admin());

-- Document status changes reach the "New production" screen live.
alter publication supabase_realtime add table public.documents;

-- ── storage: private bucket, service role only (files reach browsers via /files/{ticket}) ─
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 26214400,
        array['application/pdf', 'text/markdown', 'text/plain'])
on conflict (id) do nothing;
