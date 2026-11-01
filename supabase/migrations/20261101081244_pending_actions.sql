-- Pending actions (plan/2026-11-01c, Phase 2): what "i confirm", "do it" and "apply it" are answers to.
-- A director card that offers ONE edit leaves a row here: the edit, the card and option it belongs to, and
-- an expiry (24 h). At most one is open per thread. The director_chat function writes and closes rows with
-- the service role; the browser can only read them. The card itself stays the authority (a row is only
-- honoured while its card still waits for a choice), so a missing or stale row costs a confirmation, never
-- an edit.

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
