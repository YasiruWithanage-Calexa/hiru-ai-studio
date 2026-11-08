-- Sable, the production assistant chat (plan/2026-11-08 §4.8): its threads live in chat_threads beside the scene
-- chats, one person's each; the thread keeps a summary of its older messages; each reply's record (tiers, tools,
-- the quote guard) is kept apart from the message, where no browser can read it.
-- Schema v18 (Database/schema_v18.sql, upgrade_v17_to_v18.sql).
--
-- Every existing thread, and every thread Zora or the classic chat inserts, gets chat = 'scene' (the default): their
-- code and their queries do not change and nothing is backfilled. Only Sable's repository sets 'sable' and filters on it.

alter table public.chat_threads
  add column if not exists chat text not null default 'scene',
  add column if not exists summary text not null default '',
  add column if not exists summarised integer not null default 0;
do $$ begin
  alter table public.chat_threads add constraint chat_threads_chat_check check (chat in ('scene', 'sable'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.chat_threads add constraint chat_threads_summarised_check check (summarised >= 0);
exception when duplicate_object then null; end $$;
-- A Sable thread belongs to the production, never to a scene (the scene in view is per message).
do $$ begin
  alter table public.chat_threads add constraint chat_threads_sable_no_scene check (chat = 'scene' or scene_id is null);
exception when duplicate_object then null; end $$;
create index if not exists chat_threads_sable_idx on public.chat_threads (production_id, created_by, updated_at desc)
  where chat = 'sable';
comment on column public.chat_threads.chat is
  'scene = a scene''s chat (classic or Zora); sable = one person''s Sable thread (plan/2026-11-08 §4.8)';
comment on column public.chat_threads.summary is
  'Sable: what the older messages said, folded in once the thread is long (plan/2026-11-08 §4.5)';
comment on column public.chat_threads.summarised is 'Sable: how many of the oldest messages the summary covers';

-- A scene chat's threads are read by everyone who can see the production, as before; a Sable thread only by the
-- person who made it (D3), and its messages likewise.
drop policy if exists chat_threads_read on public.chat_threads;
create policy chat_threads_read on public.chat_threads
  for select to authenticated using (
    public.can_view_production(production_id) and (chat = 'scene' or created_by = (select auth.uid())));
drop policy if exists chat_messages_read on public.chat_messages;
create policy chat_messages_read on public.chat_messages
  for select to authenticated using (
    public.can_view_production(production_id) and exists (
      select 1 from public.chat_threads t
      where t.id = chat_messages.thread_id and (t.chat = 'scene' or t.created_by = (select auth.uid()))));

-- chat_turn_meta: one Sable reply's record ({tier_start, tier_end, escalated_by, reason, route_rule, tools, tool_errors,
-- guard, stopped, failed}: contracts/sable/events.py TurnMeta). Read by `hiru-ai review` and the lab with the service
-- role; an admin may read it; no member's browser ever does (plan/2026-11-08 rule 1: no tier or model reaches a person).
create table if not exists public.chat_turn_meta (
  message_id    uuid primary key references public.chat_messages (id) on delete cascade,
  production_id uuid not null references public.productions (id) on delete cascade,
  meta          jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);
create index if not exists chat_turn_meta_production_idx on public.chat_turn_meta (production_id, created_at);
comment on table public.chat_turn_meta is
  'A Sable reply''s record (tiers, tools, the quote guard); never read by a member''s browser (plan/2026-11-08)';
alter table public.chat_turn_meta enable row level security;
drop policy if exists chat_turn_meta_read on public.chat_turn_meta;
create policy chat_turn_meta_read on public.chat_turn_meta
  for select to authenticated using ((select public.is_admin()));
