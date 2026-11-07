-- A first frame is a DRAFT (painted at low quality, to settle the picture) or a FINAL (medium quality). One accepted
-- frame per shot AND stage: the accepted final opens the video prompt, the accepted draft is what a final may be
-- painted from (`draft_id`). Rows from before stages are finals. Nothing else changes: uploads and carried frames are finals.
alter table public.first_frames
  add column if not exists stage text not null default 'final' check (stage in ('draft', 'final'));
alter table public.first_frames
  add column if not exists draft_id uuid references public.first_frames (id) on delete set null;
alter table public.first_frames
  add constraint first_frames_draft_final check (draft_id is null or stage = 'final');

drop index if exists public.first_frames_one_accepted;
create unique index first_frames_one_accepted on public.first_frames (shot_id, stage) where accepted_at is not null;
create index first_frames_draft_idx on public.first_frames (draft_id);

comment on column public.first_frames.stage is
  'draft = painted at low quality to settle the picture; final = medium quality, the one that opens the video prompt.';
comment on column public.first_frames.draft_id is
  'The accepted draft this final was painted from (attached as a reference); null = painted without one.';
