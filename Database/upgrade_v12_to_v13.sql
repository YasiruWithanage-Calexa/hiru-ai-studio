-- ═══════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v12 to schema v13 (Shot Planner Jonathan, plan/2026-11-06b: scenes.jonathan, and
-- 'jonathan' as a planner a shot may name).
--
-- Safe to re-run: every statement skips what already exists.
--
-- HOW TO APPLY: only on a project that already has schema v12. SQL Editor → paste this whole file → Run, once. A NEW project runs
-- schema_v13.sql instead (v12 + this file gives the same schema as v13). NOT RUN YET: applying it to the hosted project is the
-- person's decision.
-- ═══════════════════════════════════════════════════════════
begin;

alter table public.scenes add column if not exists jonathan jsonb not null default '{}'::jsonb;
alter table public.shots drop constraint if exists shots_planner_check;
alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam', 'david', 'jonathan'));

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam), david (Shot Planner David) or jonathan (Shot Planner Jonathan).';
comment on column public.scenes.jonathan is
  'contracts.jonathan.stored.StoredPlan: Shot Planner Jonathan''s plan as written (the treatment, the sequences, the shots with their kept seconds), what code mended and what each revise pass changed, what is left reported, the end state the next scene starts from, the link to the scene before and the additions a person removed. {} for a scene Jonathan never planned.';

commit;
