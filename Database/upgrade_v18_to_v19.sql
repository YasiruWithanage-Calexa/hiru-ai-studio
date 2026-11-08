-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v18 to schema v19 (Shot Planner Raphael, plan/2026-11-08e:
-- scenes.raphael, 'raphael' as a shot's planner, and the clip fields on shots: role, priority, slate, handle_in_s,
-- handle_out_s, stage, anchor, blend).
--
-- Safe to re-run: every statement skips what already exists, and the planner check is dropped and made again. Nothing is
-- backfilled: every existing scene and shot keeps the defaults (no Raphael result, stage 0), so every other planner reads
-- and writes exactly as before.
--
-- HOW TO APPLY: only on a project that already has schema v18. SQL Editor → paste this whole file → Run, once. A NEW
-- project runs schema_v19.sql instead (v18 + this file gives the same schema as v19). Raphael stays unused until it is
-- applied and a production chooses it (`settings.shot_planner = 'raphael'`) or a director presses "Plan with Raphael".
-- Nothing is applied to the hosted project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.scenes add column if not exists raphael jsonb not null default '{}'::jsonb;

alter table public.shots drop constraint if exists shots_planner_check;
alter table public.shots add constraint shots_planner_check
  check (planner in ('classic', 'adam', 'david', 'jonathan', 'raphael'));

alter table public.shots
  add column if not exists role         text not null default '',
  add column if not exists priority     text not null default '',
  add column if not exists slate        text not null default '',
  add column if not exists handle_in_s  numeric(4, 2) not null default 0,
  add column if not exists handle_out_s numeric(4, 2) not null default 0,
  add column if not exists stage        smallint not null default 0,
  add column if not exists anchor       jsonb not null default '[]'::jsonb,
  add column if not exists blend        text not null default '';
do $$ begin
  alter table public.shots add constraint shots_priority_check check (priority in ('', 'must', 'should', 'nice'));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.shots add constraint shots_stage_check check (stage in (0, 1, 2));
exception when duplicate_object then null; end $$;
do $$ begin
  alter table public.shots add constraint shots_blend_check
    check (blend in ('', 'cut_in', 'under_line', 'open', 'close', 'transition'));
exception when duplicate_object then null; end $$;

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam), david (Shot Planner David), jonathan (Shot Planner Jonathan) or raphael (Shot Planner Raphael).';
comment on column public.scenes.raphael is
  'contracts.raphael.stored.StoredRaphael: Shot Planner Raphael''s result as written (the intended cut, the must clips and the cinematic clips with their designs, the editor and blend notes, the moment review, what is left reported, the length cap used and the seconds against it). {} for a scene Raphael never planned.';
comment on column public.shots.stage is
  'Raphael: 1 = a must clip (stage 1), 2 = a cinematic clip (stage 2); 0 = not a Raphael shot.';
comment on column public.shots.anchor is
  'Raphael: for a cinematic clip, the slates of the must clips it sits with.';

commit;
