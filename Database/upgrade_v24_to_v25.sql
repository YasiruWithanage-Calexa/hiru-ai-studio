-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v24 to schema v25 (the Scene board, plan/2026-11-14 §3.8):
-- `scene_boards`, one mannequin storyboard per scene, versioned, in parts of at most 16 / 12 panels; and
-- `first_frames.board_id`, the approved board a final first frame was painted from (a frame has a draft or a board,
-- never both).
--
-- Safe to re-run. Nothing is backfilled: frames painted before this stay as they are (no board_id), and a scene has no
-- board until a person paints one. The API refuses a new first frame of a painted shot without the scene's approved,
-- current board (D3); it answers "Approve the scene board first" until this file is applied and a board approved.
--
-- HOW TO APPLY: only on a project that already has schema v24 (apply upgrade_v23_to_v24.sql first). SQL Editor → paste this
-- whole file → Run, once. A NEW project runs schema_v25.sql instead (v24 + this file gives the same schema as v25). Nothing
-- is applied to the hosted project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

create table if not exists public.scene_boards (
  id             uuid primary key default gen_random_uuid(),
  production_id  uuid not null references public.productions (id) on delete cascade,
  scene_id       uuid not null references public.scenes (id) on delete cascade,
  version        int  not null default 1 check (version >= 1),
  part           int  not null default 1 check (part >= 1),
  parts          int  not null default 1 check (parts >= 1),
  status         text not null default 'queued'
                   check (status in ('queued', 'running', 'done', 'failed', 'refused')),
  job_id         uuid references public.jobs (id) on delete set null,
  quality        text not null default 'low' check (quality in ('low', 'medium')),   -- D2: never high
  storage_path   text,                                    -- frames bucket, boards/<id>/board.png; never sent to a browser
  sheet_path     text,                                    -- frames bucket, boards/<id>/sheet.png (numbers drawn by code)
  writer         jsonb not null default '{}'::jsonb,      -- {world, geography, panels:[{shot, zone, camera, background,
                                                          --   picture, people:[{name, state}]}], conflicts:[...]}
  colours        jsonb not null default '{}'::jsonb,      -- {entity_id: "red", ...}
  cells          jsonb not null default '[]'::jsonb,      -- [{shot_id, number, kind, panel, box, path, pin, text,
                                                          --   locked, note}]
  prompt         text not null default '',
  checks         jsonb not null default '[]'::jsonb,
  error          text,
  approved_at    timestamptz,
  approved_by    uuid references public.profiles (id) on delete set null,
  created_by     uuid references public.profiles (id) on delete set null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  constraint scene_boards_part_in_parts check (part <= parts),
  constraint scene_boards_approved_done check (approved_at is null or status = 'done'),
  constraint scene_boards_approved_by check (approved_by is null or approved_at is not null)
);
create unique index if not exists scene_boards_version_part on public.scene_boards (scene_id, version, part);
-- One approved board per scene AND part (like first_frames_one_accepted): approving another moves the approval.
create unique index if not exists scene_boards_one_approved on public.scene_boards (scene_id, part)
  where approved_at is not null;
create index if not exists scene_boards_production_idx on public.scene_boards (production_id);
create index if not exists scene_boards_job_idx on public.scene_boards (job_id);
create index if not exists scene_boards_approved_by_idx on public.scene_boards (approved_by);
create index if not exists scene_boards_created_by_idx on public.scene_boards (created_by);
drop trigger if exists scene_boards_touch on public.scene_boards;
create trigger scene_boards_touch before update on public.scene_boards
  for each row execute function public.touch_updated_at();

-- RLS as first_frames: production members read; every write goes through the API (service role).
alter table public.scene_boards enable row level security;
drop policy if exists scene_boards_read on public.scene_boards;
create policy scene_boards_read on public.scene_boards
  for select to authenticated using (public.can_view_production(production_id));

alter table public.first_frames add column if not exists board_id uuid
  references public.scene_boards (id) on delete set null;
alter table public.first_frames drop constraint if exists first_frames_draft_or_board;
alter table public.first_frames add constraint first_frames_draft_or_board
  check (draft_id is null or board_id is null);
create index if not exists first_frames_board_idx on public.first_frames (board_id);

comment on table public.scene_boards is
  'The Scene board (plan/2026-11-14): one mannequin storyboard per scene and version, in parts (D5). Only an approved, current board feeds first frames (D3).';
comment on column public.scene_boards.cells is
  'One per shot of the part, in order: a painted panel (panel, box, path, pin = contracts.board.plan_pin at paint time, locked, note) or a black plate (kind black, text).';
comment on column public.first_frames.board_id is
  'The approved Scene board this final was painted from (its panel attached as the approved draft); null = painted without one.';

do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'scene_boards') then
    alter publication supabase_realtime add table public.scene_boards;
  end if;
end $$;

notify pgrst, 'reload schema';

commit;
