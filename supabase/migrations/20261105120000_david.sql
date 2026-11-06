-- Shot Planner David (plan/2026-11-05e, Phase 3): the one shared migration.
--
--   scenes.david    contracts.david.stored.StoredPlan: the author's plan as written, what code mended and what a repair
--                   changed, what is left reported, the end state the next scene starts from, the look changes, the link to
--                   the scene before and the additions a person removed. `{}` for a scene David never planned.
--   shots.planner   gains 'david': David writes the same shots rows as the classic planner and Adam, with `ir` and `design`
--                   already current, so the shot producer asks neither the DoP nor the critic.
--
-- The production's choice of planner is `productions.settings.shot_planner` ('classic' | 'adam' | 'david') and the order
-- of its scenes `settings.david_order` ('linked' | 'episode'): keys in the existing settings JSON, no column. No new table
-- and no new policy: the existing read policies cover the column, and the API and the functions write it with the service
-- role. Deleting David leaves this column unused.

alter table public.scenes add column david jsonb not null default '{}'::jsonb;

alter table public.shots drop constraint shots_planner_check;
alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam', 'david'));

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam) or david (Shot Planner David).';
comment on column public.scenes.david is
  'contracts.david.stored.StoredPlan: Shot Planner David''s plan as written, what code mended and a repair changed, what is left reported, the end state the next scene starts from, look changes, the link to the scene before and the additions a person removed. {} for a scene David never planned.';
