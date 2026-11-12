-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v23 (v22 plus the canon refine, plan/2026-11-12c §3.3: canon_versions.source may be
-- 'refine' and canon_versions.provenance says where each refined field came from; canon_entities.class and parent_id;
-- canon_looks.origin; scene_looks.condition, why and origin; canon_refine_apply()). Run it once on an EMPTY project; an
-- existing project runs upgrade_v22_to_v23.sql. Nothing is applied to the hosted project until the person says so. The
-- v22 notes follow, unchanged.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v22 (v21 plus one change, plan/2026-11-12 §3.2: canon_versions.source may be
-- 'inferred', a thing the script implies but does not name). Run it once on an EMPTY project; an existing project runs
-- upgrade_v21_to_v22.sql. Nothing is applied to the hosted project until the person says so. The v21 notes follow,
-- unchanged.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v21 (v20 plus the scene breakdown, plan/2026-11-11 §5: source_memories, one per
-- uploaded document, written once; breakdown_memories, one per production, the one source today's columns are filled
-- from; scene_packets, each scene's packet with what it waits for and the script version it was built for). Run it once
-- on an EMPTY project; an existing project runs upgrade_v20_to_v21.sql. Nothing is applied to the hosted project until
-- the person says so. The v20 notes follow, unchanged.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v20. Same tables, columns, policies and seed as schema v19: v20 adds nothing new. It
-- exists so a NEW project has one file that matches upgrade_v19_to_v20.sql, the repair for a project that was missing the
-- scene-cost schema (`prices`, `token_usage.scene_id`; both are in this file, from v17). An existing project runs
-- upgrade_v19_to_v20.sql (or the missing upgrade_vN files in order), never this file.
-- Nothing is applied to the hosted project until the person says so.
-- The v19 notes follow, unchanged.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — database schema v19 (v18 plus Shot Planner Raphael, plan/2026-11-08e: scenes.raphael, 'raphael' as a
-- shot's planner and the clip fields on shots: role, priority, slate, handle_in_s, handle_out_s, stage, anchor, blend;
-- v18 is v17 plus Sable, the production assistant chat, plan/2026-11-08:
-- chat_threads.chat / summary / summarised, the per-person read policies of chat_threads and chat_messages, and the
-- chat_turn_meta table; v17 is v16 plus a scene's production cost, plan/2026-11-06d: the `prices` table and
-- token_usage.scene_id; v16 is v15 plus the document reader, plan/2026-11-06f: documents.reading_path /
-- read_from, scenes.read_from / read_confirmed_by / read_confirmed_at; v15 is v14 plus draft and final first frames: first_frames.stage and first_frames.draft_id, one
-- accepted frame per shot AND stage). v14 is v13 plus in-app video generation, plan/2026-11-06c: the video_renders table, takes.origin,
-- takes.render_id and shots.video_settings; and Zora's undo history, plan/2026-11-06e: scene_plan_revisions). v13 is v12 plus Shot Planner Jonathan, plan/2026-11-06b: scenes.jonathan and 'jonathan' as a
-- planner a shot may name. v12 is v11 plus token_usage.reasoning_tokens, plan/2026-11-05. v11 is v10 plus
-- Shot Planner Adam: a card on each shot, which planner made it,
-- and the plan Adam keeps on a scene; plan/2026-11-04b). Everything else is v10, which is v9 plus the
-- per-component columns of token_usage (plan/2026-11-04); v9 is: Phases 0–5, the director chat's marks on a shot, the cinematography terms
-- and character looks: people, roles, productions, jobs, documents, RAG store, craft techniques,
-- token usage; episodes, scenes, shots, dialogue, canon, build questions; director personas and
-- board, chat, production memory; shot designs, first frames, video prompts, frame and
-- reference-sheet buckets; takes and the takes bucket, the monthly usage budget;
-- shots.person_edits; the cinematography columns on craft_techniques; canon_looks; scene_looks;
-- shots.intent, scenes.coverage and first_frames.checks; pending_actions.
--
-- HOW TO APPLY: Supabase dashboard → SQL Editor → paste this whole file → Run, on an EMPTY
-- project. It runs in one transaction: if any statement fails, nothing is created.
-- It is the same schema as supabase/migrations/20261023000000 … 20261108120000 combined, except v15's
-- first_frames.stage / draft_id, which has no migration file yet
-- (v7 was verified that way; v8, v9 and v10 were not: see Database/README.md).
-- A project already on v9: run upgrade_v9_to_v10.sql instead (Database/README.md).
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
create type public.canon_kind as enum ('character', 'location', 'prop');

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
  -- doc_ingest keeps the normalised text (pages separated by form feeds) so later engines read
  -- the script without parsing the PDF again.
  text_path       text,
  -- The document reader (plan/2026-11-06f): the stored reading (contracts.doc_read.Reading) and how it was read.
  reading_path    text,
  read_from       text check (read_from in ('text', 'pages')),
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
-- The cinematography terms database (src/knowledge_base/cinematography) is richer than the
-- camera_shots table: what a technique FEELS like (`effect`), the phrase that makes an AI video
-- model render it (`prompt_phrase`), whether it renders reliably (`ai_supported`), mood / scene
-- tags, and the terms it pairs with (`related`: [{type, name}]). Existing rows keep working: every
-- new column has a default. `domain` now also takes light, post, story, format and animation.
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
  slug          text    not null default '',
  subcategory   text    not null default '',
  effect        text    not null default '',
  example_scene text    not null default '',
  prompt_phrase text    not null default '',
  aliases       text    not null default '',
  complexity    text    not null default '' check (complexity in ('', 'basic', 'intermediate', 'advanced')),
  ai_supported  boolean not null default true,
  tags          text[]  not null default '{}',
  related       jsonb   not null default '[]'::jsonb,
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
  component          text    not null default '',   -- 'agent:chat_answerer'; '' for the legacy engines
  component_version  integer not null default 0,
  prompt_hash        text    not null default '',
  tool_calls         integer not null default 0,    -- tool calls the model's answer asked for
  tool_result_tokens integer not null default 0,    -- tokens of tool results the call was sent
  reasoning_tokens   integer not null default 0,    -- of output_tokens, the hidden reasoning (plan/2026-11-05)
  created_at    timestamptz not null default now()
);
create index token_usage_month_idx on public.token_usage (created_at);
create index token_usage_actor_idx on public.token_usage (actor_user_id);
create index token_usage_job_idx on public.token_usage (job_id);
create index token_usage_production_idx on public.token_usage (production_id);
create index token_usage_component_idx on public.token_usage (component, created_at) where component <> '';

-- ── canon ────────────────────────────────────────────────────────────────────────────────
create table public.canon_entities (
  id                 uuid primary key default gen_random_uuid(),
  production_id      uuid not null references public.productions (id) on delete cascade,
  kind               public.canon_kind not null,
  code               text not null check (code ~ '^[CLP][0-9]{2,3}$'),
  name               text not null check (char_length(name) between 1 and 120),
  aliases            text[] not null default '{}',
  core               boolean not null default false,
  locked             boolean not null default false,
  locked_by          uuid references public.profiles (id) on delete set null,
  locked_at          timestamptz,
  current_version_id uuid,                                  -- fk added below (circular)
  -- plan/2026-11-12c: place set|vehicle|region|spot|unseen, thing prop|mentioned; only sets, vehicles, props are painted
  class              text check (class is null or class in ('set', 'vehicle', 'region', 'spot', 'unseen', 'prop', 'mentioned')),
  parent_id          uuid references public.canon_entities (id) on delete set null,  -- a spot's set or vehicle
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (production_id, code)
);
create unique index canon_entities_name_key on public.canon_entities (production_id, kind, lower(name));
create index canon_entities_locked_by_idx on public.canon_entities (locked_by);
create index canon_entities_parent_idx on public.canon_entities (parent_id);
create trigger canon_entities_touch before update on public.canon_entities
  for each row execute function public.touch_updated_at();

create table public.canon_versions (
  id               uuid primary key default gen_random_uuid(),
  entity_id        uuid not null references public.canon_entities (id) on delete cascade,
  production_id    uuid not null references public.productions (id) on delete cascade,
  version          integer not null check (version >= 1),
  card             jsonb not null default '{}'::jsonb,       -- contracts.canon.CanonCard
  card_hash        text not null,                            -- unchanged card → no new version
  wardrobe_anchor  text not null default '',
  voice_pin        text not null default '',
  reference_prompt text not null default '',
  reference_assets jsonb not null default '[]'::jsonb,       -- storage paths of reference sheets
  source           text not null default 'extract' check (source in ('extract', 'user', 'inferred', 'refine')),
  provenance       jsonb not null default '{}'::jsonb,       -- field -> {source, line, reason} (plan/2026-11-12c)
  created_by       uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  unique (entity_id, version)
);
create index canon_versions_production_idx on public.canon_versions (production_id);
create index canon_versions_created_by_idx on public.canon_versions (created_by);

alter table public.canon_entities
  add constraint canon_entities_current_version_fkey
  foreign key (current_version_id) references public.canon_versions (id) on delete set null;
create index canon_entities_current_version_idx on public.canon_entities (current_version_id);

create table public.canon_looks (
  id            uuid primary key default gen_random_uuid(),
  entity_id     uuid not null references public.canon_entities (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  name          text not null check (char_length(name) between 1 and 120),
  -- Inclusive episode numbers: [{"from": 1, "to": 20}, {"from": 44, "to": 44}]
  ranges        jsonb not null default '[]'::jsonb check (jsonb_typeof(ranges) = 'array'),
  outfit        text not null default '',
  hair          text not null default '',
  makeup        text not null default '',
  accessories   text not null default '',                  -- jewelry, watch, cap, glasses, bag
  status        text not null default 'draft' check (status in ('draft', 'ready')),
  sheet_assets  jsonb not null default '[]'::jsonb,        -- look sheets in the `references` bucket, newest first
  origin        text not null default 'person' check (origin in ('person', 'refine')),  -- plan/2026-11-12c
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index canon_looks_name_key on public.canon_looks (entity_id, lower(name));
create index canon_looks_production_idx on public.canon_looks (production_id);
create index canon_looks_created_by_idx on public.canon_looks (created_by);
create trigger canon_looks_touch before update on public.canon_looks
  for each row execute function public.touch_updated_at();

-- ── episodes, scenes, shots ──────────────────────────────────────────────────────────────
create table public.episodes (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  number        integer not null check (number >= 1),
  title         text not null default '',
  synopsis      text not null default '',
  status        text not null default 'draft' check (status in ('draft', 'building', 'ready', 'approved')),
  source_document_ids uuid[] not null default '{}',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (production_id, number)
);
create trigger episodes_touch before update on public.episodes
  for each row execute function public.touch_updated_at();

create table public.scenes (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  episode_id     uuid not null references public.episodes (id) on delete cascade,
  number         integer not null check (number >= 1),
  heading        text not null default '',
  title          text not null default '',
  location_id    uuid references public.canon_entities (id) on delete set null,
  time_of_day    text not null default '',
  envelope_s     integer not null check (envelope_s >= 4),
  script         jsonb not null default '[]'::jsonb,         -- [contracts.production.ScriptBlock]
  script_version integer not null default 1,
  status         text not null default 'draft' check (status in ('draft', 'split', 'approved')),
  note           text not null default '',
  fit_report     jsonb not null default '{}'::jsonb,         -- the split kernel's issues and totals
  locked_by      uuid references public.profiles (id) on delete set null,
  locked_at      timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (episode_id, number),
  coverage       jsonb not null default '{}'::jsonb,         -- contracts.staging.ScenePlan (plan 2026-11-01)
  reading        jsonb not null default '{}'::jsonb,         -- contracts.reading.SceneReading (plan 2026-11-01d)
  staging        jsonb not null default '{}'::jsonb,         -- contracts.stagemap.SceneStaging (plan 2026-11-01d)
  adam           jsonb not null default '{}'::jsonb,         -- contracts.adam.stored.StoredPlan (plan 2026-11-04b)
  david          jsonb not null default '{}'::jsonb,         -- contracts.david.stored.StoredPlan (plan 2026-11-05e)
  jonathan       jsonb not null default '{}'::jsonb,         -- contracts.jonathan.stored.StoredPlan (plan 2026-11-06b)
  raphael        jsonb not null default '{}'::jsonb,         -- contracts.raphael.stored.StoredRaphael (plan 2026-11-08e)
  -- The document reader (plan/2026-11-06f decision 6): how the script was read (null = the rules), and the person who
  -- checked a 'pages' scene's dialogue against the page.
  read_from         text check (read_from in ('text', 'pages')),
  read_confirmed_by uuid references public.profiles (id) on delete set null,
  read_confirmed_at timestamptz
);
create index scenes_production_idx on public.scenes (production_id);
create index scenes_location_idx on public.scenes (location_id);
create index scenes_locked_by_idx on public.scenes (locked_by);
create index scenes_read_confirmed_by_idx on public.scenes (read_confirmed_by);

-- token_usage.scene_id: the scene a call was for (null = not tied to one scene, e.g. a whole-episode breakdown).
alter table public.token_usage add column scene_id uuid references public.scenes (id) on delete set null;
create index token_usage_scene_idx on public.token_usage (scene_id, created_at);
comment on column public.token_usage.scene_id is
  'The scene this call was made for (plan/2026-11-06d). Null for work on a whole episode or production.';
create trigger scenes_touch before update on public.scenes
  for each row execute function public.touch_updated_at();

create table public.shots (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  scene_id       uuid not null references public.scenes (id) on delete cascade,
  number         integer not null check (number >= 1),
  title          text not null default '',
  framing        text not null default 'MS'
                   check (framing in ('WIDE', 'MS', 'MCU', 'CU', 'TWO', 'OTS', 'INSERT')),
  duration_s     integer not null check (duration_s in (4, 6, 8)),   -- 10 s stays off (PLAN.md Q4)
  start_s        integer not null default 0,
  sound_mode     text not null default 'ambient'
                   check (sound_mode in ('dialogue', 'voiceover', 'sung', 'ambient', 'music_only', 'silent')),
  camera_link    text not null default 'cut' check (camera_link in ('cut', 'continuous', 'match')),
  frame_strategy text not null default 'generate'
                   check (frame_strategy in ('generate', 'carry_last_frame', 'storyboard')),
  speaker_id     uuid references public.canon_entities (id) on delete set null,
  beats          jsonb not null default '[]'::jsonb,
  block_start    integer not null default 0,
  block_end      integer not null default 0,
  word_target    integer not null default 0,
  words          integer not null default 0,
  ir             jsonb not null default '{}'::jsonb,         -- shot producer IR (Phase 4)
  status         text not null default 'draft' check (status in ('draft', 'frame', 'prompt')),
  version        integer not null default 1,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- a length a PERSON chose: re-timing keeps it and reports what overruns (PLAN.md §6.1)
  duration_locked boolean not null default false,
  -- Phase 4. `design`: the DP's camera recommendation, its reasons and pins (shot_producer).
  -- `camera_overrides`: the fields a PERSON changed (the API only), so a re-design never undoes them.
  design           jsonb not null default '{}'::jsonb,
  camera_overrides jsonb not null default '{}'::jsonb,
  -- `person_edits`: what a PERSON set on the shot (who is in it, advisories to ignore, the DoP's note;
  -- contracts.producer.PersonEdits). The API and director_chat write it; no agent does.
  person_edits     jsonb not null default '{}'::jsonb,
  -- an edit renumbers shots in one upsert, keeping their ids (frames and prompts hang off them):
  -- the numbers are unique again by the end of the transaction, not after every row
  constraint shots_scene_id_number_key unique (scene_id, number) deferrable initially deferred,
  -- plan 2026-11-01: what the shot is for and who the camera sees (contracts.staging.ShotIntent)
  intent           jsonb not null default '{}'::jsonb,
  -- plan 2026-11-04b: Shot Planner Adam. `card` is contracts.adam.plan.ShotCard ({} for a classic shot); `planner`
  -- says which planner made the shot. Both planners write the same rows, so everything after the plan works.
  card             jsonb not null default '{}'::jsonb,
  -- plan 2026-11-05e adds 'david': Shot Planner David writes the same rows, with `ir` and `design` already current.
  -- plan 2026-11-06b adds 'jonathan': Shot Planner Jonathan writes the same rows the same way.
  planner          text  not null default 'classic' check (planner in ('classic', 'adam', 'david', 'jonathan', 'raphael')),
  role             text  not null default '',          -- Raphael (plan/2026-11-08e): master, single, ots, reaction, insert ...
  priority         text  not null default '' check (priority in ('', 'must', 'should', 'nice')),
  slate            text  not null default '',          -- 12B-3: scene 12, setup B, the third clip of that setup
  handle_in_s      numeric(4, 2) not null default 0,   -- seconds of the take before the action starts
  handle_out_s     numeric(4, 2) not null default 0,
  stage            smallint not null default 0 check (stage in (0, 1, 2)),   -- 0 not Raphael's, 1 must bin, 2 cinematic pass
  anchor           jsonb not null default '[]'::jsonb, -- a cinematic clip: the slates of the must clips it sits with
  blend            text  not null default '' check (blend in ('', 'cut_in', 'under_line', 'open', 'close', 'transition'))
);
create index shots_production_idx on public.shots (production_id);
create index shots_speaker_idx on public.shots (speaker_id);
create trigger shots_touch before update on public.shots
  for each row execute function public.touch_updated_at();

comment on column public.shots.card is
  'contracts.adam.plan.ShotCard: the director''s card for this shot. {} for a shot the classic planner made.';
comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam), david (Shot Planner David), jonathan (Shot Planner Jonathan) or raphael (Shot Planner Raphael).';
comment on column public.scenes.adam is
  'contracts.adam.stored.StoredPlan: Shot Planner Adam''s analysis, treatments, moments, staging, sound map, reports and the elaborations a person removed. {} for a scene Adam never planned.';
comment on column public.scenes.david is
  'contracts.david.stored.StoredPlan: Shot Planner David''s plan as written, what code mended and a repair changed, what is left reported, the end state the next scene starts from, look changes, the link to the scene before and the additions a person removed. {} for a scene David never planned.';
comment on column public.scenes.jonathan is
  'contracts.jonathan.stored.StoredPlan: Shot Planner Jonathan''s plan as written (the treatment, the sequences, the shots with their kept seconds), what code mended and what each revise pass changed, what is left reported, the end state the next scene starts from, the link to the scene before and the additions a person removed. {} for a scene Jonathan never planned.';
comment on column public.scenes.raphael is
  'contracts.raphael.stored.StoredRaphael: Shot Planner Raphael''s result as written (the intended cut, the must clips and the cinematic clips with their designs, the editor and blend notes, the moment review, what is left reported, the length cap used and the seconds against it). {} for a scene Raphael never planned.';
comment on column public.shots.stage is
  'Raphael: 1 = a must clip (stage 1), 2 = a cinematic clip (stage 2); 0 = not a Raphael shot.';
comment on column public.shots.anchor is
  'Raphael: for a cinematic clip, the slates of the must clips it sits with.';

create table public.dialogue_lines (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid not null references public.scenes (id) on delete cascade,
  ord           integer not null check (ord >= 0),
  speaker       text not null,                               -- as written in the script
  character_id  uuid references public.canon_entities (id) on delete set null,
  text          text not null,                               -- verbatim; engines never rewrite it
  delivery      text not null default '',
  -- plan 2026-11-01c: a translated line keeps the words it was written in (the first original, kept through
  -- every later translation); both null for a line nobody translated
  source_text   text,
  source_lang   text,
  words         integer not null default 0,
  shot_id       uuid references public.shots (id) on delete set null,
  beat_index    integer,
  start_s       real,
  overrun_s     real not null default 0,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  -- a script edit inserts, deletes and reorders lines in one upsert (ids kept)
  constraint dialogue_lines_scene_id_ord_key unique (scene_id, ord) deferrable initially deferred,
  constraint dialogue_lines_source_pair check ((source_text is null) = (source_lang is null))
);
create index dialogue_lines_production_idx on public.dialogue_lines (production_id);
create index dialogue_lines_character_idx on public.dialogue_lines (character_id);
create index dialogue_lines_shot_idx on public.dialogue_lines (shot_id);
create trigger dialogue_lines_touch before update on public.dialogue_lines
  for each row execute function public.touch_updated_at();

-- ── build questions ──────────────────────────────────────────────────────────────────────
create table public.questions (
  id            uuid primary key,                            -- deterministic per job + key
  production_id uuid not null references public.productions (id) on delete cascade,
  job_id        uuid references public.jobs (id) on delete set null,
  key           text not null,                               -- what it is about, stable across retries
  agent         text not null default '',
  scope         text not null default '',
  title         text not null,
  body          text not null,
  options       jsonb not null default '[]'::jsonb,
  allow_text    boolean not null default false,
  status        text not null default 'open' check (status in ('open', 'answered', 'defaulted')),
  answer        jsonb,
  answered_by   uuid references public.profiles (id) on delete set null,
  answered_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index questions_production_idx on public.questions (production_id, status, created_at);
create index questions_job_idx on public.questions (job_id, status);
create index questions_answered_by_idx on public.questions (answered_by);
create trigger questions_touch before update on public.questions
  for each row execute function public.touch_updated_at();

-- ── personas (a global library) and the board ────────────────────────────────────────────
create table public.director_personas (
  id         uuid primary key default gen_random_uuid(),
  slug       text not null unique check (slug ~ '^[a-z0-9-]{2,60}$'),
  name       text not null,
  initials   text not null check (char_length(initials) between 1 and 3),
  color      text not null default '#2F3A45' check (color ~ '^#[0-9A-Fa-f]{6}$'),
  specialty  text not null default '',
  traits     jsonb not null default '[]'::jsonb,           -- [{label, value 0-100}]
  style_note text not null default '',
  charter    text not null default '',                      -- the persona's directing brief, used in prompts
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger director_personas_touch before update on public.director_personas
  for each row execute function public.touch_updated_at();

create table public.production_director_board (
  production_id uuid not null references public.productions (id) on delete cascade,
  persona_id    uuid not null references public.director_personas (id) on delete cascade,
  seat          text not null check (seat in ('lead', 'advisor')),
  added_by      uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  primary key (production_id, persona_id)
);
create unique index production_director_board_one_lead
  on public.production_director_board (production_id) where seat = 'lead';
create index production_director_board_persona_idx on public.production_director_board (persona_id);
create index production_director_board_added_by_idx on public.production_director_board (added_by);

-- ── chat ─────────────────────────────────────────────────────────────────────────────────
create table public.chat_threads (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid references public.scenes (id) on delete cascade,
  title         text not null default '',
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  -- Sable (plan/2026-11-08 §4.8): 'scene' = a scene's chat (classic or Zora); 'sable' = one person's Sable thread, which
  -- belongs to the production and never to a scene. The summary folds in its older messages (§4.5).
  chat          text not null default 'scene',
  summary       text not null default '',
  summarised    integer not null default 0,
  constraint chat_threads_chat_check check (chat in ('scene', 'sable')),
  constraint chat_threads_summarised_check check (summarised >= 0),
  constraint chat_threads_sable_no_scene check (chat = 'scene' or scene_id is null)
);
create index chat_threads_sable_idx on public.chat_threads (production_id, created_by, updated_at desc)
  where chat = 'sable';
comment on column public.chat_threads.chat is
  'scene = a scene''s chat (classic or Zora); sable = one person''s Sable thread (plan/2026-11-08 §4.8)';
comment on column public.chat_threads.summary is
  'Sable: what the older messages said, folded in once the thread is long (plan/2026-11-08 §4.5)';
comment on column public.chat_threads.summarised is 'Sable: how many of the oldest messages the summary covers';
create index chat_threads_production_idx on public.chat_threads (production_id, scene_id);
create index chat_threads_scene_idx on public.chat_threads (scene_id);
create index chat_threads_created_by_idx on public.chat_threads (created_by);
create trigger chat_threads_touch before update on public.chat_threads
  for each row execute function public.touch_updated_at();

create table public.chat_messages (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  thread_id      uuid not null references public.chat_threads (id) on delete cascade,
  kind           text not null check (kind in ('user', 'director')),
  author_user_id uuid references public.profiles (id) on delete set null,
  persona_id     uuid references public.director_personas (id) on delete set null,
  speaker        text not null default '',
  tone           text check (tone in ('lead', 'board')),
  text           text not null default '',
  blocks         jsonb not null default '[]'::jsonb,
  ops            jsonb not null default '[]'::jsonb,       -- operations the turn applied
  citations      jsonb not null default '[]'::jsonb,
  created_at     timestamptz not null default now()
);
create index chat_messages_thread_idx on public.chat_messages (thread_id, created_at);
create index chat_messages_production_idx on public.chat_messages (production_id);
create index chat_messages_author_idx on public.chat_messages (author_user_id);
create index chat_messages_persona_idx on public.chat_messages (persona_id);

-- chat_turn_meta: one Sable reply's record ({tier_start, tier_end, escalated_by, reason, route_rule, tools, tool_errors,
-- guard, stopped, failed}: contracts/sable/events.py TurnMeta). Read by `hiru-ai review` and the lab with the service
-- role; an admin may read it; no member's browser ever does (plan/2026-11-08 rule 1: no tier or model reaches a person).
create table public.chat_turn_meta (
  message_id    uuid primary key references public.chat_messages (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  meta          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index chat_turn_meta_production_idx on public.chat_turn_meta (production_id, created_at);
comment on table public.chat_turn_meta is
  'A Sable reply''s record (tiers, tools, the quote guard); never read by a member''s browser (plan/2026-11-08)';

-- ── production memory (PLAN.md §6.2) ─────────────────────────────────────────────────────
-- Approved decisions, director notes and answered questions, retrieved like documents (each
-- item is also indexed in `chunks` as corpus 'memory', source 'memory:<id>').
create table public.memory_items (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  scene_id      uuid references public.scenes (id) on delete set null,
  kind          text not null check (kind in ('decision', 'note', 'answer')),
  text          text not null check (char_length(text) between 1 and 2000),
  source_ref    jsonb not null default '{}'::jsonb,         -- {"message_id"} / {"question_id"} ...
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now()
);
create index memory_items_production_idx on public.memory_items (production_id, created_at desc);
create index memory_items_scene_idx on public.memory_items (scene_id);
create index memory_items_created_by_idx on public.memory_items (created_by);

-- ── first frames ─────────────────────────────────────────────────────────────────────────
create table public.first_frames (
  id              uuid primary key default gen_random_uuid(),
  production_id   uuid not null references public.productions (id) on delete cascade,
  shot_id         uuid not null references public.shots (id) on delete cascade,
  job_id          uuid references public.jobs (id) on delete set null,
  status          text not null default 'queued'
                    check (status in ('queued', 'running', 'done', 'failed', 'refused')),
  storage_path    text,                                     -- frames bucket; never sent to a browser
  prompt          text not null default '',                 -- the exact image prompt used
  reference_ids   uuid[] not null default '{}',             -- canon entities whose sheets were attached
  pins            jsonb not null default '{}'::jsonb,       -- contracts.producer.Pins at render time
  error           text,
  rejected_reason text,
  accepted_at     timestamptz,
  accepted_by     uuid references public.profiles (id) on delete set null,
  created_by      uuid references public.profiles (id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check (accepted_by is null or accepted_at is not null),
  check (accepted_at is null or status = 'done'),
  checks          jsonb not null default '[]'::jsonb,       -- [contracts.producer.Check] on the painted frame
  stage           text not null default 'final' check (stage in ('draft', 'final')),  -- draft = low quality, final = medium
  draft_id        uuid references public.first_frames (id) on delete set null,        -- the accepted draft a final was painted from
  constraint first_frames_draft_final check (draft_id is null or stage = 'final')
);
-- One accepted frame per shot AND stage: accepting another moves the choice (picking is free). The accepted final opens the
-- video prompt; the accepted draft is what a final may be painted from.
create unique index first_frames_one_accepted on public.first_frames (shot_id, stage) where accepted_at is not null;
create index first_frames_draft_idx on public.first_frames (draft_id);
create index first_frames_shot_idx on public.first_frames (shot_id, created_at);
create index first_frames_production_idx on public.first_frames (production_id);
create index first_frames_job_idx on public.first_frames (job_id);
create index first_frames_accepted_by_idx on public.first_frames (accepted_by);
create index first_frames_created_by_idx on public.first_frames (created_by);
create trigger first_frames_touch before update on public.first_frames
  for each row execute function public.touch_updated_at();

-- ── video prompts (versioned per shot) ───────────────────────────────────────────────────
create table public.video_prompts (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  shot_id       uuid not null references public.shots (id) on delete cascade,
  version       integer not null check (version >= 1),
  sections      jsonb not null default '[]'::jsonb,         -- [contracts.producer.PromptSection]
  prose         text not null default '',                   -- the plain text, as copied to Flow
  model         text not null default '',                   -- "Veo 3.1 · 8 s · 16:9"
  ir            jsonb not null default '{}'::jsonb,         -- the IR it was serialized from
  camera        jsonb not null default '{}'::jsonb,         -- the camera as it stood
  checks        jsonb not null default '[]'::jsonb,
  frame_id      uuid references public.first_frames (id) on delete set null,
  pins          jsonb not null default '{}'::jsonb,
  job_id        uuid references public.jobs (id) on delete set null,
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  unique (shot_id, version)
);
create index video_prompts_production_idx on public.video_prompts (production_id);
create index video_prompts_frame_idx on public.video_prompts (frame_id);
create index video_prompts_job_idx on public.video_prompts (job_id);
create index video_prompts_created_by_idx on public.video_prompts (created_by);

-- ── takes ────────────────────────────────────────────────────────────────────────────────
create table public.takes (
  id              uuid primary key default gen_random_uuid(),
  production_id   uuid not null references public.productions (id) on delete cascade,
  shot_id         uuid not null references public.shots (id) on delete cascade,
  prompt_id       uuid references public.video_prompts (id) on delete set null,
  prompt_version  integer,                                  -- the version it was generated from
  storage_path    text not null,                            -- takes bucket; never sent to a browser
  mime            text not null check (mime in ('video/mp4', 'video/quicktime', 'video/webm')),
  bytes           bigint not null check (bytes > 0),
  duration_s      real,                                     -- probed; null when the probe failed
  status          text not null default 'uploaded' check (status in ('uploaded', 'accepted', 'rejected')),
  reason          text,                                     -- why it was rejected
  last_frame_path text,                                     -- frames bucket, once extracted
  uploaded_by     uuid references public.profiles (id) on delete set null,
  accepted_by     uuid references public.profiles (id) on delete set null,
  accepted_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check ((status = 'accepted') = (accepted_at is not null))
);
-- One accepted take per shot: accepting another moves the choice.
create unique index takes_one_accepted on public.takes (shot_id) where status = 'accepted';
create index takes_shot_idx on public.takes (shot_id, created_at);
create index takes_production_idx on public.takes (production_id);
create index takes_prompt_idx on public.takes (prompt_id);
create index takes_uploaded_by_idx on public.takes (uploaded_by);
create index takes_accepted_by_idx on public.takes (accepted_by);
create trigger takes_touch before update on public.takes
  for each row execute function public.touch_updated_at();

-- ── the monthly usage budget (model tokens; the UI shows a percentage only) ──────────────
create table public.usage_budget (
  month         date primary key check (extract(day from month) = 1),
  budget_tokens bigint not null check (budget_tokens > 0),
  set_by        uuid references public.profiles (id) on delete set null,
  updated_at    timestamptz not null default now()
);
create index usage_budget_set_by_idx on public.usage_budget (set_by);
create trigger usage_budget_touch before update on public.usage_budget
  for each row execute function public.touch_updated_at();

-- prices: one row per price and start date. kind 'tokens' = per million tokens, matched by the longest model_prefix;
-- 'video_second' = per second of video, matched by engine + model ('' = any) + resolution; 'estimate' = one frame or
-- one prompt (model_prefix 'frame' | 'prompt'), used only when no history says what one costs. Micro-dollars (1 USD =
-- 1,000,000) so no float is ever summed. Read by admins only; the API reads and adds prices with the service role.
create table public.prices (
  id                  uuid primary key default gen_random_uuid(),
  kind                text not null check (kind in ('tokens', 'video_second', 'estimate')),
  model_prefix        text not null default '',
  engine              text not null default '',
  model               text not null default '',
  resolution          text not null default '',
  input_micros        bigint not null default 0 check (input_micros >= 0),
  cached_input_micros bigint not null default 0 check (cached_input_micros >= 0),
  output_micros       bigint not null default 0 check (output_micros >= 0),
  per_second_micros   bigint not null default 0 check (per_second_micros >= 0),
  unit_micros         bigint not null default 0 check (unit_micros >= 0),
  valid_from          timestamptz not null default now(),
  note                text not null default '',
  set_by              uuid references public.profiles (id) on delete set null,
  created_at          timestamptz not null default now()
);
create index prices_kind_idx on public.prices (kind, valid_from desc);
create index prices_set_by_idx on public.prices (set_by);
comment on table public.prices is
  'The dated price list behind a scene''s cost (plan/2026-11-06d). Rows are added, never edited: a change applies to work made after its valid_from.';

-- ── LangGraph checkpoints ────────────────────────────────────────────────────────────────
-- The checkpointer (langgraph-checkpoint-postgres) creates and migrates its own tables in this
-- schema the first time a function connects. Not exposed through the API; no browser access.
create schema if not exists graph;
revoke all on schema graph from public, anon, authenticated;

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
  use_case text, example_film text, score double precision,
  slug text, subcategory text, effect text, example_scene text, prompt_phrase text,
  aliases text, complexity text, ai_supported boolean, tags text[], related jsonb
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
         t.example_film, f.score::double precision,
         t.slug, t.subcategory, t.effect, t.example_scene, t.prompt_phrase,
         t.aliases, t.complexity, t.ai_supported, t.tags, t.related
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

-- ── usage ────────────────────────────────────────────────────────────────────────────────
-- Monthly model-token total for GET /v1/usage (the UI shows a percentage only).
-- Called by the API with the service role; browser roles have no use for it.
create or replace function public.token_usage_since(since timestamptz)
returns bigint
language sql stable
set search_path = ''
as $$
  select coalesce(sum(input_tokens::bigint + output_tokens::bigint), 0)::bigint
  from public.token_usage
  where created_at >= since;
$$;

revoke all on function public.token_usage_since(timestamptz) from public, anon, authenticated;
grant execute on function public.token_usage_since(timestamptz) to service_role;

-- ── canon refine (plan/2026-11-12c §3.4) ─────────────────────────────────────────────────
-- Writes a canon refine's answer in ONE transaction, so readers see all of the old canon or all of the new:
--   1. every new version is inserted (never current yet); a card the entity already has (same card_hash) is reused,
--      so a re-run with the same answer inserts nothing;
--   2. an entity switches to its new version only if its current version is the one the job read
--      (expected_version_id), that version came from extract, inferred or refine, and the entity is not locked;
--   3. otherwise the new version stays a proposal (inserted, not current) for a person to accept;
--   4. draft looks are added where the character has no look of that name (a person's look is never replaced), and a
--      scene look is written only where no person chose one (origin 'person' wins).
-- Called by the canon refine job with the service role; browser roles have no use for it.
create or replace function public.canon_refine_apply(p_production uuid, p_payload jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  v jsonb;
  item jsonb;
  ent public.canon_entities%rowtype;
  cur_source text;
  ver_id uuid;
  next_no integer;
  chosen uuid;
  n integer;
  switched integer := 0;
  proposed integer := 0;
  changed integer := 0;
  kept integer := 0;
  looks_made integer := 0;
  scene_looks_made integer := 0;
  actor uuid := nullif(p_payload->>'actor', '')::uuid;
begin
  for v in select value from jsonb_array_elements(coalesce(p_payload->'versions', '[]'::jsonb)) loop
    select * into ent from public.canon_entities
      where id = (v->>'entity_id')::uuid and production_id = p_production
      for update;
    if not found then
      continue;
    end if;
    ver_id := null;
    select cv.id into ver_id from public.canon_versions cv
      where cv.entity_id = ent.id and cv.card_hash = v->>'card_hash'
      order by cv.version desc limit 1;
    if ver_id is null then
      select coalesce(max(cv.version), 0) + 1 into next_no from public.canon_versions cv where cv.entity_id = ent.id;
      insert into public.canon_versions (entity_id, production_id, version, card, card_hash, wardrobe_anchor,
                                         voice_pin, reference_prompt, source, provenance, created_by)
      values (ent.id, p_production, next_no, coalesce(v->'card', '{}'::jsonb), v->>'card_hash',
              coalesce(v->>'wardrobe_anchor', ''), coalesce(v->>'voice_pin', ''),
              coalesce(v->>'reference_prompt', ''), 'refine', coalesce(v->'provenance', '{}'::jsonb), actor)
      returning id into ver_id;
    end if;
    if ent.current_version_id = ver_id then
      kept := kept + 1;
    elsif ent.current_version_id is distinct from nullif(v->>'expected_version_id', '')::uuid then
      changed := changed + 1;
    else
      select cv.source into cur_source from public.canon_versions cv where cv.id = ent.current_version_id;
      if not ent.locked and coalesce(cur_source, 'extract') in ('extract', 'inferred', 'refine') then
        update public.canon_entities set current_version_id = ver_id where id = ent.id;
        switched := switched + 1;
      else
        proposed := proposed + 1;
      end if;
    end if;
    if v ? 'class' and (not ent.locked or ent.class is null) then
      update public.canon_entities
        set class = nullif(v->>'class', ''),
            parent_id = (select p.id from public.canon_entities p
                          where p.id = nullif(v->>'parent_id', '')::uuid and p.production_id = p_production
                            and p.id <> ent.id)
        where id = ent.id;
    end if;
  end loop;

  for item in select value from jsonb_array_elements(coalesce(p_payload->'looks', '[]'::jsonb)) loop
    insert into public.canon_looks (entity_id, production_id, name, ranges, outfit, hair, makeup, accessories,
                                    status, origin, created_by)
    select e.id, p_production, item->>'name', coalesce(item->'ranges', '[]'::jsonb), coalesce(item->>'outfit', ''),
           coalesce(item->>'hair', ''), coalesce(item->>'makeup', ''), coalesce(item->>'accessories', ''),
           'draft', 'refine', actor
      from public.canon_entities e
      where e.id = (item->>'entity_id')::uuid and e.production_id = p_production and e.kind = 'character'
    on conflict (entity_id, lower(name)) do nothing;
    get diagnostics n = row_count;
    looks_made := looks_made + n;
  end loop;

  for item in select value from jsonb_array_elements(coalesce(p_payload->'scene_looks', '[]'::jsonb)) loop
    chosen := null;
    select l.id into chosen from public.canon_looks l
      where l.entity_id = (item->>'entity_id')::uuid and l.production_id = p_production
        and lower(l.name) = lower(item->>'look_name');
    if chosen is null
       or not exists (select 1 from public.scenes s
                       where s.id = (item->>'scene_id')::uuid and s.production_id = p_production) then
      continue;
    end if;
    insert into public.scene_looks (scene_id, entity_id, look_id, production_id, condition, why, origin)
    values ((item->>'scene_id')::uuid, (item->>'entity_id')::uuid, chosen, p_production,
            coalesce(item->>'condition', ''), coalesce(item->>'why', ''), 'refine')
    on conflict (scene_id, entity_id) do update
      set look_id = excluded.look_id, condition = excluded.condition, why = excluded.why
      where public.scene_looks.origin = 'refine';
    get diagnostics n = row_count;
    scene_looks_made := scene_looks_made + n;
  end loop;

  return jsonb_build_object('switched', switched, 'proposed', proposed, 'skipped_changed', changed,
                            'unchanged', kept, 'looks', looks_made, 'scene_looks', scene_looks_made);
end;
$$;

revoke all on function public.canon_refine_apply(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.canon_refine_apply(uuid, jsonb) to service_role;

-- what the canon refine's columns mean (plan/2026-11-12c)
comment on column public.canon_versions.source is
  'extract: read from a document;
comment on column public.canon_versions.provenance is
  'field -> {source: script|inferred, line, reason}: where each refined value came from (plan/2026-11-12c)';
comment on column public.canon_entities.class is
  'place: set, vehicle, region, spot, unseen;
comment on column public.canon_entities.parent_id is 'a spot''s set or vehicle (plan/2026-11-12c)';
comment on column public.scene_looks.condition is
  'the state of the outfit and the person in this scene only (wet from the rain, lying still);

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
alter table public.canon_entities     enable row level security;
alter table public.canon_versions     enable row level security;
alter table public.canon_looks    enable row level security;
alter table public.episodes           enable row level security;
alter table public.scenes             enable row level security;
alter table public.shots              enable row level security;
alter table public.dialogue_lines     enable row level security;
alter table public.questions          enable row level security;
alter table public.director_personas          enable row level security;
alter table public.production_director_board  enable row level security;
alter table public.chat_threads               enable row level security;
alter table public.chat_messages              enable row level security;
alter table public.chat_turn_meta             enable row level security;
alter table public.memory_items               enable row level security;
alter table public.first_frames               enable row level security;
alter table public.video_prompts              enable row level security;
alter table public.takes                      enable row level security;
alter table public.usage_budget               enable row level security;

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

create policy canon_entities_read on public.canon_entities
  for select to authenticated using (public.can_view_production(production_id));
create policy canon_versions_read on public.canon_versions
  for select to authenticated using (public.can_view_production(production_id));
create policy canon_looks_read on public.canon_looks
  for select to authenticated using (public.can_view_production(production_id));
create policy episodes_read on public.episodes
  for select to authenticated using (public.can_view_production(production_id));
create policy scenes_read on public.scenes
  for select to authenticated using (public.can_view_production(production_id));
create policy shots_read on public.shots
  for select to authenticated using (public.can_view_production(production_id));
create policy dialogue_lines_read on public.dialogue_lines
  for select to authenticated using (public.can_view_production(production_id));
create policy questions_read on public.questions
  for select to authenticated using (public.can_view_production(production_id));
create policy director_personas_read on public.director_personas
  for select to authenticated using ((select public.is_active_user()));
create policy production_director_board_read on public.production_director_board
  for select to authenticated using (public.can_view_production(production_id));
-- A scene chat's threads are read by everyone who can see the production; a Sable thread only by the person who made
-- it (plan/2026-11-08 D3), and its messages likewise. A Sable reply's record only by an admin.
create policy chat_threads_read on public.chat_threads
  for select to authenticated using (
    public.can_view_production(production_id) and (chat = 'scene' or created_by = (select auth.uid())));
create policy chat_messages_read on public.chat_messages
  for select to authenticated using (
    public.can_view_production(production_id) and exists (
      select 1 from public.chat_threads t
      where t.id = chat_messages.thread_id and (t.chat = 'scene' or t.created_by = (select auth.uid()))));
create policy chat_turn_meta_read on public.chat_turn_meta
  for select to authenticated using ((select public.is_admin()));
create policy memory_items_read on public.memory_items
  for select to authenticated using (public.can_view_production(production_id));
create policy first_frames_read on public.first_frames
  for select to authenticated using (public.can_view_production(production_id));
create policy video_prompts_read on public.video_prompts
  for select to authenticated using (public.can_view_production(production_id));
create policy takes_read on public.takes
  for select to authenticated using (public.can_view_production(production_id));

-- ── realtime ─────────────────────────────────────────────────────────────────────────────
-- The browser follows job progress and document status live (RLS applies to Realtime).
alter publication supabase_realtime add table public.jobs, public.job_events, public.documents;
-- The live build tree and its questions; new chat messages and board changes reach everyone on
-- the scene.
alter publication supabase_realtime add table
  public.episodes, public.scenes, public.shots, public.questions, public.canon_entities;
alter publication supabase_realtime add table public.chat_messages, public.production_director_board;
-- Frames land one by one while a person watches the Production panel.
alter publication supabase_realtime add table public.first_frames, public.video_prompts;
alter publication supabase_realtime add table public.takes;

-- ── the persona library: generic archetypes, not real people ─────────────────────────────
insert into public.director_personas (slug, name, initials, color, specialty, traits, style_note, charter) values
  ('grounded-realist', 'Grounded Realist', 'GR', '#2F3A45', 'Naturalistic family drama',
   '[{"label":"Realism","value":85},{"label":"Tone","value":40},{"label":"Pacing","value":40},{"label":"Audience","value":60}]',
   'Available light, held frames, restraint with close-ups.',
   'Prefer eye-level framing and steady, motivated camera. Hold on reactions rather than cutting away. Save close-ups for the moment a decision lands. Light from practical sources: lamps, windows, the fire.'),
  ('classic-teledrama', 'Classic Teledrama', 'CT', '#5A3E2B', 'Prime-time Sri Lankan teledrama',
   '[{"label":"Realism","value":55},{"label":"Tone","value":70},{"label":"Pacing","value":55},{"label":"Audience","value":85}]',
   'Clear coverage, readable emotion, family-audience warmth.',
   'Cover every speaker clearly: establish, then singles in shot / reverse shot. Emotion should read from across a living room. Keep the geography obvious and the axis steady.'),
  ('tension-builder', 'Tension Builder', 'TB', '#1F2A44', 'Suspense and turning points',
   '[{"label":"Realism","value":65},{"label":"Tone","value":30},{"label":"Pacing","value":70},{"label":"Audience","value":55}]',
   'Withheld information, slow push-ins, silence before the turn.',
   'Delay the reveal. Use slow push-ins and inserts of objects that matter. Let silence sit before a line that changes the scene. Tighten the frame as the stakes rise.'),
  ('short-form', 'Short-Form Storyteller', 'SF', '#3D4F2F', 'Vertical cut-downs for social',
   '[{"label":"Realism","value":50},{"label":"Tone","value":60},{"label":"Pacing","value":85},{"label":"Audience","value":75}]',
   'A hook in the first shot, faces close, every second earns its place.',
   'Open on the most arresting image. Favour closer framings that read on a phone. Keep shots short and the speaker centred for vertical frames. Cut on action.'),
  ('lyrical-eye', 'Lyrical Eye', 'LE', '#4A2F4F', 'Mood, landscape and music-led moments',
   '[{"label":"Realism","value":45},{"label":"Tone","value":55},{"label":"Pacing","value":30},{"label":"Audience","value":50}]',
   'Landscape as feeling, golden light, music carrying the cut.',
   'Let place carry emotion: wide frames of sea, sky and village life between the drama. Use golden-hour and lamp light. Let music-only shots breathe at the turns of a scene.');

-- ── storage: private buckets, service role only (files reach browsers via /files/{ticket}) ─
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('documents', 'documents', false, 26214400,
        array['application/pdf', 'text/markdown', 'text/plain'])
on conflict (id) do nothing;
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('frames', 'frames', false, 15728640, array['image/png', 'image/jpeg', 'image/webp']),
       ('references', 'references', false, 15728640, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do nothing;
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('takes', 'takes', false, 31457280, array['video/mp4', 'video/quicktime', 'video/webm'])
on conflict (id) do nothing;


-- Scene looks: which look of a character this scene uses. A person picks it in the Director panel's
-- Canon tab. A scene with no pick for a character follows the episode rule (the narrowest ready
-- look that covers the episode). One row per character per scene; deleting the row goes back to
-- the rule. Shape of a row: contracts.canon.SceneLook.
--
-- Same access model as before: RLS is READ-ONLY for browser roles; the API writes.

create table public.scene_looks (
  scene_id      uuid not null references public.scenes (id) on delete cascade,
  entity_id     uuid not null references public.canon_entities (id) on delete cascade,
  look_id       uuid not null references public.canon_looks (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  chosen_by     uuid references public.profiles (id) on delete set null,
  -- plan/2026-11-12c: the scene's condition (wet, lying still), never part of the look; why; who chose it
  condition     text not null default '',
  why           text not null default '',
  origin        text not null default 'person' check (origin in ('person', 'refine')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (scene_id, entity_id)
);
create index scene_looks_look_idx on public.scene_looks (look_id);
create index scene_looks_entity_idx on public.scene_looks (entity_id);
create index scene_looks_production_idx on public.scene_looks (production_id);
create index scene_looks_chosen_by_idx on public.scene_looks (chosen_by);
create trigger scene_looks_touch before update on public.scene_looks
  for each row execute function public.touch_updated_at();

alter table public.scene_looks enable row level security;
create policy scene_looks_read on public.scene_looks
  for select to authenticated using (public.can_view_production(production_id));

-- plan/2026-11-01c (Phase 2): pending actions. A director card that offers one edit leaves a row here so
-- that "i confirm" / "do it" is answered in code. Browsers read, the director_chat function writes.
create table public.pending_actions (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  thread_id     uuid not null references public.chat_threads (id) on delete cascade,
  scene_id      uuid not null references public.scenes (id) on delete cascade,
  message_id    uuid not null references public.chat_messages (id) on delete cascade,
  block         integer not null check (block >= 0),   -- index of the options block in the message
  option        integer not null check (option >= 0),  -- index of the option in that block
  intent        text not null default '',              -- the goal the option claims (contracts.director_capabilities)
  label         text not null default '',
  ops           jsonb not null default '[]'::jsonb,    -- the option's edit, pinned to shot and block ids
  status        text not null default 'open'
                check (status in ('open', 'applied', 'closed', 'expired', 'superseded')),
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  closed_at     timestamptz
);
create unique index pending_actions_one_open on public.pending_actions (thread_id) where status = 'open';
create index pending_actions_production_idx on public.pending_actions (production_id);
create index pending_actions_scene_idx on public.pending_actions (scene_id);
create index pending_actions_message_idx on public.pending_actions (message_id);
create index pending_actions_created_by_idx on public.pending_actions (created_by);

alter table public.pending_actions enable row level security;
create policy pending_actions_read on public.pending_actions
  for select to authenticated using (public.can_view_production(production_id));

-- v9 (plan/2026-11-01): staging and second looks.
comment on column public.shots.intent is
  'contracts.staging.ShotIntent: purpose, what we see, emotional beat, who is on screen or only heard. by = model | rules | person; an agent never replaces a person''s.';
comment on column public.scenes.coverage is
  'contracts.staging.ScenePlan: the scene''s axis, motif and size progression. by = model | rules | person.';
comment on column public.first_frames.checks is
  '[contracts.producer.Check]: advisories on a painted frame (a missing reference sheet; a vision model''s look at it).';
comment on column public.first_frames.stage is
  'draft = painted at low quality to settle the picture; final = medium quality, the one that opens the video prompt.';
comment on column public.first_frames.draft_id is
  'The accepted draft this final was painted from (attached as a reference); null = painted without one.';
comment on column public.scenes.reading is
  'contracts.reading.SceneReading: what the scene is about, where the feeling turns, what to hold. by = model | rules | person; a person''s reading is never replaced by the system, a script edit only marks it stale.';

comment on column public.scenes.staging is
  'contracts.stagemap.SceneStaging: the scene''s spots and where each person is, block by block. Checked in code for teleports, crossed lines and eyelines. by = model | person; a person''s map is never replaced.';

-- plan/2026-11-05d: production memory. What a document says about how to make the drama (look, sound, feel,
-- performance, edit), one entry per instruction, quoting the document. Browsers read, the memory_reader and a person write.
create table public.production_memory (
  id            uuid primary key default gen_random_uuid(),
  production_id uuid not null references public.productions (id) on delete cascade,
  document_id   uuid references public.documents (id) on delete cascade,   -- null when a person wrote it
  topic         text not null check (topic = lower(topic) and char_length(topic) between 1 and 40),
  applies_to    text not null default 'production'
                check (applies_to ~ '^(production|(place|character|when):.+|episode:[1-9][0-9]*)$'),
  says          text not null check (char_length(says) between 1 and 2000),
  quote         text not null default '' check (char_length(quote) <= 2000),   -- the document's own words
  strength      text not null default 'prefer' check (strength in ('must', 'prefer', 'fact')),
  status        text not null default 'draft' check (status in ('draft', 'approved', 'rejected')),
  source        text not null default 'reader' check (source in ('reader', 'person')),
  created_by    uuid references public.profiles (id) on delete set null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index production_memory_production_idx on public.production_memory (production_id, status);
create index production_memory_document_idx on public.production_memory (document_id);
create index production_memory_created_by_idx on public.production_memory (created_by);

comment on table public.production_memory is
  'Direction a document gives about how to make the drama (look, sound, feel, performance, edit), one entry per instruction, quoting the document. Read by the production_memory middleware; written by the memory_reader at ingest and by a person.';
comment on column public.production_memory.applies_to is
  'production | place:<name> | character:<name> | episode:<n> | when:<the situation, in words>. place and character names are matched to canon when read, not when written.';

alter table public.production_memory enable row level security;
create policy production_memory_read on public.production_memory
  for select to authenticated using (public.can_view_production(production_id));

-- ── in-app video generation (plan/2026-11-06c): a take can be made in Hiru, not only uploaded from Flow ─────
-- video_renders: one row per take asked for (the exact request, its seed, its status, the take it made). takes.origin and
-- takes.render_id say where a take came from; shots.video_settings holds a shot's own video settings and reference list.
-- The production default is a key in productions.settings (`video`), no column. Browsers read only.
create table public.video_renders (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  shot_id        uuid not null references public.shots (id) on delete cascade,
  job_id         uuid references public.jobs (id) on delete set null,
  status         text not null default 'queued'
                   check (status in ('queued', 'running', 'done', 'failed', 'refused')),
  engine         text not null,
  model          text not null,
  spec           jsonb not null,                      -- contracts.video_gen.RenderSpec, exactly as sent (no image bytes)
  request_hash   text not null,
  seed           bigint check (seed is null or seed between 0 and 4294967295),   -- null only for an engine that takes none
  prompt_id      uuid references public.video_prompts (id) on delete set null,
  provider_id    text,                                -- Omni interaction id / Veo operation name: resume, later extend/edit
  take_id        uuid references public.takes (id) on delete set null,          -- the take it made
  error          text,                                -- written for people, never a provider's own text
  refusal        text,
  usage          jsonb not null default '{}'::jsonb,  -- tokens or seconds, latency, bytes; never shown
  created_by     uuid references public.profiles (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index video_renders_shot_idx on public.video_renders (shot_id, created_at);
create index video_renders_production_idx on public.video_renders (production_id, status);
create index video_renders_job_idx on public.video_renders (job_id);
create index video_renders_prompt_idx on public.video_renders (prompt_id);
create index video_renders_take_idx on public.video_renders (take_id);
create index video_renders_created_by_idx on public.video_renders (created_by);
create trigger video_renders_touch before update on public.video_renders
  for each row execute function public.touch_updated_at();

comment on table public.video_renders is
  'One take asked for from Omni Flash or Veo: the exact request (RenderSpec without image bytes), its seed and status, and the take it made on success. Inserted queued by the API, claimed by the video_render function.';
comment on column public.video_renders.provider_id is
  'The provider''s id for the job (Omni interaction id, Veo operation name), written the moment submit returns so a re-delivered task polls instead of submitting again.';

alter table public.takes add column origin text not null default 'upload' check (origin in ('upload', 'generated'));
alter table public.takes add column render_id uuid references public.video_renders (id) on delete set null;
create index takes_render_idx on public.takes (render_id);
comment on column public.takes.origin is 'upload = brought back from Flow; generated = made in Hiru (video_renders).';

alter table public.shots add column video_settings jsonb not null default '{}'::jsonb;
comment on column public.shots.video_settings is
  'contracts.video_gen.ShotVideoState: this shot''s video setting overrides and its reference list once a person has touched it. {} = Hiru''s choice.';

alter table public.video_renders enable row level security;
create policy video_renders_read on public.video_renders
  for select to authenticated using (public.can_view_production(production_id));

alter publication supabase_realtime add table public.video_renders;

-- Zora's undo history (plan/2026-11-06e §4.7): scene_plan_revisions.
create table public.scene_plan_revisions (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  scene_id       uuid not null references public.scenes (id) on delete cascade,
  revision       integer not null check (revision > 0),
  kind           text not null check (kind in ('base', 'turn', 'use', 'undo', 'redo')),
  restores       integer check (restores is null or restores > 0),
  stored         jsonb not null,                       -- scenes.jonathan after the change
  shot_ids       jsonb not null default '[]'::jsonb,   -- the shot id of each number, in order
  made_by        uuid references public.profiles (id) on delete set null,
  message_id     uuid references public.chat_messages (id) on delete set null,
  created_at     timestamptz not null default now(),
  unique (scene_id, revision)
);
create index scene_plan_revisions_production_idx on public.scene_plan_revisions (production_id);
create index scene_plan_revisions_made_by_idx on public.scene_plan_revisions (made_by);
create index scene_plan_revisions_message_idx on public.scene_plan_revisions (message_id);

comment on table public.scene_plan_revisions is
  'Zora''s undo history of a scene''s Jonathan plan: the whole stored plan after each change, the shot ids by number, and which revision an undo or redo restored. Written by the zora_chat function; the last 30 per scene are kept.';

alter table public.scene_plan_revisions enable row level security;
create policy scene_plan_revisions_read on public.scene_plan_revisions
  for select to authenticated using (public.can_view_production(production_id));

-- ── a scene's production cost (plan/2026-11-06d) ────────────────────────────────────────
alter table public.prices enable row level security;
create policy prices_read on public.prices
  for select to authenticated using ((select public.is_admin()));

-- The seed: list prices, provisional until a real bill confirms them (Phase 0). A model or size that is not listed has no
-- price on purpose: the scene's cost then says some prices are missing.
insert into public.prices (kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros,
                           output_micros, per_second_micros, unit_micros, note, valid_from)
select v.*, timestamptz '2026-01-01 00:00:00+00' from (values
  ('tokens', 'gpt-5-nano', '', '', '', 50000, 5000, 400000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5-mini', '', '', '', 250000, 25000, 2000000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5', '', '', '', 1250000, 125000, 10000000, 0, 0, 'OpenAI list price, standard tier'),
  ('tokens', 'gpt-5.5', '', '', '', 5000000, 500000, 30000000, 0, 0, 'OpenAI list price, read 2026-11-06 by lab/cinematic: confirm'),
  ('tokens', 'gpt-6.1-sol', '', '', '', 2000000, 100000, 10000000, 0, 0, 'OpenAI list price below 272K input (2x input above it), read 2026-11-06 by lab/cinematic: confirm'),
  ('tokens', 'text-embedding-3-large', '', '', '', 130000, 130000, 0, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('tokens', 'text-embedding-3-small', '', '', '', 20000, 20000, 0, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('tokens', 'gpt-image-2', '', '', '', 8000000, 2000000, 30000000, 0, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1', '', '720p', 0, 0, 0, 400000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1', '', '1080p', 0, 0, 0, 400000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1_fast', '', '720p', 0, 0, 0, 100000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'veo_3_1_fast', '', '1080p', 0, 0, 0, 120000, 0, 'list price, provisional: confirm against a real bill (plan/2026-11-06d Phase 0)'),
  ('video_second', '', 'omni_flash', '', '720p', 0, 0, 0, 100000, 0, 'derived from the preview''s token rate: confirm (plan/2026-11-06d Phase 0)'),
  ('estimate', 'frame', '', '', '', 0, 0, 0, 0, 80000, 'one first frame at medium quality: used only when no frame has been made yet'),
  ('estimate', 'prompt', '', '', '', 0, 0, 0, 0, 20000, 'one video prompt: used only when none has been made yet')
) as v(kind, model_prefix, engine, model, resolution, input_micros, cached_input_micros, output_micros,
       per_second_micros, unit_micros, note)
where not exists (select 1 from public.prices);

-- ── the scene breakdown (plan/2026-11-11 §5): the two memories and the scene packet ─────────────────────────
create table if not exists public.source_memories (
  document_id   uuid primary key references public.documents (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  filename      text not null check (char_length(filename) between 1 and 255),
  body          jsonb not null,                              -- contracts.breakdown.schema.SourceMemory
  created_at    timestamptz not null default now()
);
create index if not exists source_memories_production_idx on public.source_memories (production_id, created_at);
comment on table public.source_memories is
  'One document as the scene breakdown''s split read it (plan/2026-11-11 §5): written once, never edited';

create table if not exists public.breakdown_memories (
  production_id uuid primary key references public.productions (id) on delete cascade,
  body          jsonb not null,                              -- contracts.breakdown.schema.Breakdown
  version       integer not null default 1 check (version >= 1),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table public.breakdown_memories is
  'A production''s breakdown memory (plan/2026-11-11 §5, D1): the one source today''s columns are filled from';
drop trigger if exists breakdown_memories_touch on public.breakdown_memories;
create trigger breakdown_memories_touch before update on public.breakdown_memories
  for each row execute function public.touch_updated_at();

create table if not exists public.scene_packets (
  scene_id       uuid primary key references public.scenes (id) on delete cascade,
  production_id  uuid not null references public.productions (id) on delete cascade,
  scene_key      text not null check (scene_key ~ '^E[0-9]{2,}-S[0-9]{2,}$'),   -- the memory's id: E01-S03
  packet         jsonb not null default '{}'::jsonb,         -- contracts.breakdown.packet.assemble
  waits          jsonb not null default '[]'::jsonb,         -- why planning waits; [] = complete
  script_version integer not null default 0 check (script_version >= 0),
  memory_version integer not null default 1 check (memory_version >= 1),
  updated_at     timestamptz not null default now()
);
create index if not exists scene_packets_production_idx on public.scene_packets (production_id);
comment on table public.scene_packets is
  'Each scene''s packet, what every shot planner reads (plan/2026-11-11 §7); stale when the scene''s script_version moved on';

alter table public.source_memories enable row level security;
alter table public.breakdown_memories enable row level security;
alter table public.scene_packets enable row level security;
drop policy if exists source_memories_read on public.source_memories;
create policy source_memories_read on public.source_memories
  for select to authenticated using (public.can_view_production(production_id));
drop policy if exists breakdown_memories_read on public.breakdown_memories;
create policy breakdown_memories_read on public.breakdown_memories
  for select to authenticated using (public.can_view_production(production_id));
drop policy if exists scene_packets_read on public.scene_packets;
create policy scene_packets_read on public.scene_packets
  for select to authenticated using (public.can_view_production(production_id));

commit;
