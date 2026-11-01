-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v8 to schema v9 (staging and second looks:
-- what each shot is for and who the camera sees, a scene's coverage plan and reading, checks on frames, and the
-- table of pending actions behind "i confirm" in the director chat, and the original words of a translated line).
--
-- Safe to re-run: every statement skips what already exists, so a project that already has part of v9
-- (the 2026-11-01 columns, say) can run the whole file.
--
-- HOW TO APPLY: only on a project that already has schema v8. SQL Editor → paste this whole
-- file → Run, once. It runs in one transaction: if any statement fails, nothing changes.
-- A NEW project runs schema_v9.sql instead (v8 + this file gives the same schema as v9).
-- ═══════════════════════════════════════════════════════════════════════════════════════════

begin;

-- plan/2026-11-01. All JSON, all optional; existing rows read as "not written yet". No new table
-- and no new policy: the read policies already cover these columns; the API and the functions
-- write them with the service role.

alter table public.shots add column if not exists intent jsonb not null default '{}'::jsonb;
alter table public.scenes add column if not exists coverage jsonb not null default '{}'::jsonb;
alter table public.first_frames add column if not exists checks jsonb not null default '[]'::jsonb;

comment on column public.shots.intent is
  'contracts.staging.ShotIntent: purpose, what we see, emotional beat, who is on screen or only heard. by = model | rules | person; an agent never replaces a person''s.';
comment on column public.scenes.coverage is
  'contracts.staging.ScenePlan: the scene''s axis, motif and size progression. by = model | rules | person.';
comment on column public.first_frames.checks is
  '[contracts.producer.Check]: advisories on a painted frame (a missing reference sheet; a vision model''s look at it).';

-- plan/2026-11-01d (Phase 1): a scene's reading. What the scene is about, where the feeling turns and what to hold,
-- written before the scene is cut. JSON, optional (`{}` = not written); no new policy.
alter table public.scenes add column if not exists reading jsonb not null default '{}'::jsonb;
comment on column public.scenes.reading is
  'contracts.reading.SceneReading: what the scene is about, where the feeling turns, what to hold. by = model | rules | person; a person''s reading is never replaced by the system, a script edit only marks it stale.';

-- plan/2026-11-01c (Phase 4): a translated line keeps the words it was written in. The script stays in its
-- own language by default; when a person asks for the dialogue in another language the director chat's
-- translator writes `text` and these hold the first original. Both null for a line nobody translated.
alter table public.dialogue_lines
  add column if not exists source_text text,
  add column if not exists source_lang text;
alter table public.dialogue_lines drop constraint if exists dialogue_lines_source_pair;
alter table public.dialogue_lines
  add constraint dialogue_lines_source_pair check ((source_text is null) = (source_lang is null));

-- plan/2026-11-01c (Phase 2): pending actions. A director card that offers one edit leaves a row here so
-- that "i confirm" / "do it" is answered in code. Browsers read, the director_chat function writes.
create table if not exists public.pending_actions (
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
create unique index if not exists pending_actions_one_open on public.pending_actions (thread_id) where status = 'open';
create index if not exists pending_actions_production_idx on public.pending_actions (production_id);
create index if not exists pending_actions_scene_idx on public.pending_actions (scene_id);
create index if not exists pending_actions_message_idx on public.pending_actions (message_id);
create index if not exists pending_actions_created_by_idx on public.pending_actions (created_by);

alter table public.pending_actions enable row level security;
drop policy if exists pending_actions_read on public.pending_actions;
create policy pending_actions_read on public.pending_actions
  for select to authenticated using (public.can_view_production(production_id));

commit;
