-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v14 to schema v15 (draft and final first frames: first_frames.stage and
-- first_frames.draft_id; one accepted frame per shot AND stage).
--
-- A draft is painted at low quality to settle the picture, a final at medium. The accepted final opens the video prompt; the
-- accepted draft is what a final may be painted from (`draft_id`). Rows from before this are finals. Uploads and carried frames
-- are finals.
--
-- Safe to re-run: every statement skips or replaces what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v14. SQL Editor → paste this whole file → Run, once. A NEW project runs
-- schema_v15.sql instead (v14 + this file gives the same schema as v15). Until it is applied, no first frame can be asked for:
-- the API names the stage on every new row. Nothing is applied to the hosted project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.first_frames add column if not exists stage text not null default 'final' check (stage in ('draft', 'final'));
alter table public.first_frames add column if not exists draft_id uuid references public.first_frames (id) on delete set null;
alter table public.first_frames drop constraint if exists first_frames_draft_final;
alter table public.first_frames add constraint first_frames_draft_final check (draft_id is null or stage = 'final');
drop index if exists public.first_frames_one_accepted;
create unique index first_frames_one_accepted on public.first_frames (shot_id, stage) where accepted_at is not null;
create index if not exists first_frames_draft_idx on public.first_frames (draft_id);
comment on column public.first_frames.stage is
  'draft = painted at low quality to settle the picture; final = medium quality, the one that opens the video prompt.';
comment on column public.first_frames.draft_id is
  'The accepted draft this final was painted from (attached as a reference); null = painted without one.';

commit;
