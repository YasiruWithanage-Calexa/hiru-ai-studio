-- Shot Planner Jonathan (plan/2026-11-06b, Phase 3): the one shared migration.
--
--   scenes.jonathan  contracts.jonathan.stored.StoredPlan: the plan as written (treatment, sequences, shots), what code mended and
--                    what each revise pass changed, what is left reported, the end state the next scene starts from, the link to the
--                    scene before and the additions a person removed. `{}` for a scene Jonathan never planned.
--   shots.planner    gains 'jonathan': Jonathan writes the same shots rows as the others, with `ir` and `design` already current.
--
-- The production's choice of planner is `productions.settings.shot_planner` ('classic' | 'adam' | 'david' | 'jonathan') and the order
-- of its scenes `settings.jonathan_order`: keys in the existing settings JSON, no column. No new table and no new policy. Deleting
-- Jonathan leaves this column unused.

alter table public.scenes add column jonathan jsonb not null default '{}'::jsonb;

alter table public.shots drop constraint shots_planner_check;
alter table public.shots add constraint shots_planner_check check (planner in ('classic', 'adam', 'david', 'jonathan'));

comment on column public.shots.planner is
  'Which planner made this shot: classic (script_split), adam (Shot Planner Adam), david (Shot Planner David) or jonathan (Shot Planner Jonathan).';
comment on column public.scenes.jonathan is
  'contracts.jonathan.stored.StoredPlan: Shot Planner Jonathan''s plan as written (the treatment, the sequences, the shots with their kept seconds), what code mended and what each revise pass changed, what is left reported, the end state the next scene starts from, the link to the scene before and the additions a person removed. {} for a scene Jonathan never planned.';
