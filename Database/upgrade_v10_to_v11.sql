-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v10 to schema v11 (Shot Planner Adam, plan/2026-11-04b, Phase 6:
-- a card on each shot, which planner made it, and the plan Adam keeps on a scene).
--
-- Safe to re-run: every statement skips what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v10. SQL Editor → paste this whole file → Run, once. It
-- runs in one transaction: if any statement fails, nothing changes. A NEW project runs schema_v11.sql instead (v10 +
-- this file gives the same schema as v11). Then restart the API and the functions. Until this is applied, a production
-- set to Adam cannot write its shots (the insert names the new columns); the classic planner does not touch them.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.shots
  add column if not exists card    jsonb not null default '{}'::jsonb,
  add column if not exists planner text  not null default 'classic';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'shots_planner_check' and conrelid = 'public.shots'::regclass) then
    alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam'));
  end if;
end $$;

alter table public.scenes add column if not exists adam jsonb not null default '{}'::jsonb;

comment on column public.shots.card is
  'contracts.adam.plan.ShotCard: the director''s card for this shot. {} for a shot the classic planner made.';
comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split) or adam (Shot Planner Adam).';
comment on column public.scenes.adam is
  'contracts.adam.stored.StoredPlan: Shot Planner Adam''s analysis, treatments, moments, staging, sound map, reports and the elaborations a person removed. {} for a scene Adam never planned.';

commit;
