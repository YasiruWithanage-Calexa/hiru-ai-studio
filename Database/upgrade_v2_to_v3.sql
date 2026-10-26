-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v2 to schema v3 (Phase 4: the Production
-- panel — shot designs and a person's camera, first frames, video prompts, frame and
-- reference-sheet buckets).
--
-- HOW TO APPLY: only on a project that already has schema v2. SQL Editor → paste this whole
-- file → Run, once. It runs in one transaction: if any statement fails, nothing changes.
-- A NEW project runs schema_v3.sql instead (v2 + this file gives the same schema as v3).
--
-- Nothing to re-run afterwards: existing shots start with no design and the recommended camera.
-- ═══════════════════════════════════════════════════════════════════════════════════════════

begin;

-- ── shots: the design and a person's camera ──────────────────────────────────────────────
-- `ir` (Phase 2) holds the DP's IR. `design` holds the recommendation, its reasons and pins
-- (written by shot_producer); `camera_overrides` the fields a person changed (written by the
-- API only, so a re-design never undoes a person's choice).
alter table public.shots
  add column design           jsonb not null default '{}'::jsonb,
  add column camera_overrides jsonb not null default '{}'::jsonb;

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
  check (accepted_at is null or status = 'done')
);
-- One accepted frame per shot: accepting another moves the choice (picking is free).
create unique index first_frames_one_accepted on public.first_frames (shot_id) where accepted_at is not null;
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

-- ── RLS (read-only for browser roles) ────────────────────────────────────────────────────
alter table public.first_frames  enable row level security;
alter table public.video_prompts enable row level security;

create policy first_frames_read on public.first_frames
  for select to authenticated using (public.can_view_production(production_id));
create policy video_prompts_read on public.video_prompts
  for select to authenticated using (public.can_view_production(production_id));

-- Frames land one by one while a person watches the panel.
alter publication supabase_realtime add table public.first_frames, public.video_prompts;

-- ── storage: frames and reference sheets (private; the API streams them through tickets) ─
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('frames', 'frames', false, 15728640, array['image/png', 'image/jpeg', 'image/webp']),
       ('references', 'references', false, 15728640, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do nothing;

commit;
