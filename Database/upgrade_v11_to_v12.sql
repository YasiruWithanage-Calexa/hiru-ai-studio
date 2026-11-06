-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v11 to schema v12 (token_usage.reasoning_tokens, plan/2026-11-05,
-- Phase 0: how much of a model call's output was hidden reasoning, so a cost per scene can be read from the table; and the
-- production_memory table, plan/2026-11-05d: what the documents say about how to make the drama; and Shot Planner David,
-- plan/2026-11-05e: scenes.david, and 'david' as a planner a shot may name).
--
-- Safe to re-run: every statement skips what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v11. SQL Editor → paste this whole file → Run, once. A NEW
-- project runs schema_v12.sql instead (v11 + this file gives the same schema as v12). Then set USAGE_DETAIL=true for the
-- API and the functions and restart them: a row names the column only when the run asked for the per-call detail,
-- because PostgREST refuses a row that names a column the table lacks.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.token_usage add column if not exists reasoning_tokens integer not null default 0;

comment on column public.token_usage.reasoning_tokens is
  'Of output_tokens, the part that was hidden reasoning (a reasoning model bills it as output). 0 for a legacy row.';

-- plan/2026-11-05d: production memory (a new table; the browser reads, the memory_reader and a person write).
create table if not exists public.production_memory (
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
create index if not exists production_memory_production_idx on public.production_memory (production_id, status);
create index if not exists production_memory_document_idx on public.production_memory (document_id);
create index if not exists production_memory_created_by_idx on public.production_memory (created_by);

comment on table public.production_memory is
  'Direction a document gives about how to make the drama (look, sound, feel, performance, edit), one entry per instruction, quoting the document. Read by the production_memory middleware; written by the memory_reader at ingest and by a person.';
comment on column public.production_memory.applies_to is
  'production | place:<name> | character:<name> | episode:<n> | when:<the situation, in words>. place and character names are matched to canon when read, not when written.';

alter table public.production_memory enable row level security;
drop policy if exists production_memory_read on public.production_memory;
create policy production_memory_read on public.production_memory
  for select to authenticated using (public.can_view_production(production_id));

-- plan/2026-11-05e: Shot Planner David keeps its plan on the scene and may be named as the planner of a shot.
alter table public.scenes add column if not exists david jsonb not null default '{}'::jsonb;
alter table public.shots drop constraint if exists shots_planner_check;
alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam', 'david'));

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam) or david (Shot Planner David).';
comment on column public.scenes.david is
  'contracts.david.stored.StoredPlan: Shot Planner David''s plan as written, what code mended and a repair changed, what is left reported, the end state the next scene starts from, look changes, the link to the scene before and the additions a person removed. {} for a scene David never planned.';

commit;
