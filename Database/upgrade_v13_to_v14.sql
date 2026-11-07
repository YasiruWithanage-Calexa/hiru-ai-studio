-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v13 to schema v14 (in-app video generation, plan/2026-11-06c: the
-- video_renders table, takes.origin, takes.render_id and shots.video_settings; and Zora's undo history, plan/2026-11-06e:
-- scene_plan_revisions).
--
-- Safe to re-run: every statement skips what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v13. SQL Editor → paste this whole file → Run, once. A NEW project runs
-- schema_v14.sql instead (v13 + this file gives the same schema as v14). Then set GOOGLE__API_KEY for the video_render function
-- (and the API, which only checks that it exists). Nothing is applied to the hosted project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

-- ── in-app video generation (plan/2026-11-06c): a take can be made in Hiru, not only uploaded from Flow ─────
-- video_renders: one row per take asked for (the exact request, its seed, its status, the take it made). takes.origin and
-- takes.render_id say where a take came from; shots.video_settings holds a shot's own video settings and reference list.
-- The production default is a key in productions.settings (`video`), no column. Browsers read only.
create table if not exists public.video_renders (
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
create index if not exists video_renders_shot_idx on public.video_renders (shot_id, created_at);
create index if not exists video_renders_production_idx on public.video_renders (production_id, status);
create index if not exists video_renders_job_idx on public.video_renders (job_id);
create index if not exists video_renders_prompt_idx on public.video_renders (prompt_id);
create index if not exists video_renders_take_idx on public.video_renders (take_id);
create index if not exists video_renders_created_by_idx on public.video_renders (created_by);
drop trigger if exists video_renders_touch on public.video_renders;
create trigger video_renders_touch before update on public.video_renders
  for each row execute function public.touch_updated_at();

comment on table public.video_renders is
  'One take asked for from Omni Flash or Veo: the exact request (RenderSpec without image bytes), its seed and status, and the take it made on success. Inserted queued by the API, claimed by the video_render function.';
comment on column public.video_renders.provider_id is
  'The provider''s id for the job (Omni interaction id, Veo operation name), written the moment submit returns so a re-delivered task polls instead of submitting again.';

alter table public.takes add column if not exists origin text not null default 'upload' check (origin in ('upload', 'generated'));
alter table public.takes add column if not exists render_id uuid references public.video_renders (id) on delete set null;
create index if not exists takes_render_idx on public.takes (render_id);
comment on column public.takes.origin is 'upload = brought back from Flow; generated = made in Hiru (video_renders).';

alter table public.shots add column if not exists video_settings jsonb not null default '{}'::jsonb;
comment on column public.shots.video_settings is
  'contracts.video_gen.ShotVideoState: this shot''s video setting overrides and its reference list once a person has touched it. {} = Hiru''s choice.';

alter table public.video_renders enable row level security;
drop policy if exists video_renders_read on public.video_renders;
create policy video_renders_read on public.video_renders
  for select to authenticated using (public.can_view_production(production_id));

do $$ begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'video_renders') then
    alter publication supabase_realtime add table public.video_renders;
  end if;
end $$;

-- Zora's undo history (plan/2026-11-06e §4.7): scene_plan_revisions.
create table if not exists public.scene_plan_revisions (
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
create index if not exists scene_plan_revisions_production_idx on public.scene_plan_revisions (production_id);
create index if not exists scene_plan_revisions_made_by_idx on public.scene_plan_revisions (made_by);
create index if not exists scene_plan_revisions_message_idx on public.scene_plan_revisions (message_id);

comment on table public.scene_plan_revisions is
  'Zora''s undo history of a scene''s Jonathan plan: the whole stored plan after each change, the shot ids by number, and which revision an undo or redo restored. Written by the zora_chat function; the last 30 per scene are kept.';

alter table public.scene_plan_revisions enable row level security;
drop policy if exists scene_plan_revisions_read on public.scene_plan_revisions;
create policy scene_plan_revisions_read on public.scene_plan_revisions
  for select to authenticated using (public.can_view_production(production_id));

commit;
