-- Production memory (plan/2026-11-05d, Phase 2): what a document says about HOW to make the drama, kept as a list of
-- entries for every later agent. One row is one instruction or fact (genre, a palette, a lens, a rule about sound) with
-- what it applies to and the document's own words. It is a list, not a form: a production has the rows its documents
-- gave and no empty slots for what they did not.
--
-- `memory_reader` writes rows with the service role at ingest (status 'draft', source 'reader'); the `production_memory`
-- middleware reads them for the agents that subscribe. A person approves, edits, rejects or adds rows from the memory
-- panel (plan Phase 6, after the live check); until then the browser can only read. A row a person has touched
-- (approved, rejected, or edited: source becomes 'person') is never replaced when its document is ingested again.

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
