-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v20 to schema v21 (the scene breakdown, plan/2026-11-11 §5:
-- source_memories, breakdown_memories, scene_packets, each with RLS on and a read policy for the production's members).
--
-- Safe to re-run: every statement skips what already exists. Nothing is backfilled: a production has no breakdown until a
-- structure build runs with BREAKDOWN__ENABLED=true, and with it off nothing reads or writes these tables.
--
-- HOW TO APPLY: only on a project that already has schema v20. SQL Editor → paste this whole file → Run, once. A NEW
-- project runs schema_v21.sql instead (v20 + this file gives the same schema as v21). Nothing is applied to the hosted
-- project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

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

notify pgrst, 'reload schema';

commit;
