-- In-app video generation (plan/2026-11-06c, Phase 2): a take can be MADE in Hiru with Omni Flash or Veo, not only
-- uploaded from Flow.
--
--   video_renders        one row per take asked for: the exact request (contracts.video_gen.RenderSpec, no image bytes),
--                        its seed, its status and, when it succeeds, the take it made. The API inserts it `queued`
--                        before dispatch; the video_render function CLAIMS it (queued -> running), so a Cloud Tasks
--                        re-delivery never pays for a second video. A render becomes a take only on success, so the
--                        `takes` invariants (a stored file, a mime, bytes) stay as they are.
--   takes.origin         'upload' (Flow, as before) or 'generated' (made here).
--   takes.render_id      the render that made it.
--   shots.video_settings contracts.video_gen.ShotVideoState: the shot's setting overrides and its reference list once a
--                        person has touched it. `{}` = Hiru's choice.
--
-- The production default lives in `productions.settings.video` (a key in the existing settings JSON, no column).
-- Browsers read only: no write policies, as every table. The API and the function write with the service role.

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
