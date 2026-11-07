-- Zora, the director chat over Shot Planner Jonathan's plan (plan/2026-11-06e §4.7, Phase 5): undo and redo.
--
--   scene_plan_revisions  one row per change Zora saved on a scene (and the plan before its first one, `base`): the WHOLE
--                         `scenes.jonathan` JSON after the change and the shot id of each number, so a restore re-runs
--                         the planner's write path and gives every shot its id back. An undo or a redo is itself a row
--                         (`restores` names the revision it brought back), so redo is the undo of an undo. The
--                         zora_chat function keeps the last 30 per scene (D4).
--
-- Browsers read only: no write policies, as every table. The function writes with the service role.

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
