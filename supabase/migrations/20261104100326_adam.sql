-- Shot Planner Adam (plan/2026-11-04b, Phase 6): the one shared migration. Every new column is named for what it holds.
--
--   shots.card      contracts.adam.plan.ShotCard: the director's card for this shot (size, angle, movement, focus,
--                   composition, performance per beat, where each line plays, sound in and out, the cut into it, why).
--                   `{}` for a shot the classic planner made.
--   shots.planner   which planner made the shot: 'classic' (script_split) or 'adam'. Both write the same shots rows, so
--                   everything after the plan (frames, prompts, takes) keeps working.
--   scenes.adam     contracts.adam.stored.StoredPlan: the analysis, the treatment in use and the two that were not, the
--                   moments (script, implied, elaboration), the staging, the sound map, the code's reports, the
--                   critics' notes and scores, the elaborations a person removed, and the shot list that was there
--                   before (to compare). `{}` for a scene Adam never planned.
--
-- The production's choice of planner is `productions.settings.shot_planner` ('classic' | 'adam'), a key in the existing
-- settings JSON: no column. No new table and no new policy: the existing read policies cover the columns, and the API
-- and the functions write them with the service role. Deleting Adam leaves these columns unused.

alter table public.shots
  add column card    jsonb not null default '{}'::jsonb,
  add column planner text  not null default 'classic' check (planner in ('classic', 'adam'));

alter table public.scenes add column adam jsonb not null default '{}'::jsonb;

comment on column public.shots.card is
  'contracts.adam.plan.ShotCard: the director''s card for this shot. {} for a shot the classic planner made.';
comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split) or adam (Shot Planner Adam).';
comment on column public.scenes.adam is
  'contracts.adam.stored.StoredPlan: Shot Planner Adam''s analysis, treatments, moments, staging, sound map, reports and the elaborations a person removed. {} for a scene Adam never planned.';
