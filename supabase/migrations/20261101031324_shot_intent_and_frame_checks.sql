-- Staging and second looks (plan/2026-11-01): what each shot is for and who the camera sees,
-- a scene's coverage plan, and the checks a painted frame carries. All JSON, all optional.
--
--   shots.intent        contracts.staging.ShotIntent  (the intent agent, or a person)
--   scenes.coverage     contracts.staging.ScenePlan   (axis, motif, size progression)
--   first_frames.checks [contracts.producer.Check]     (a missing sheet; what a vision model saw)
--
-- No new table and no new policy: the existing read policies cover the new columns, and the
-- API and the functions write them with the service role.

alter table public.shots add column intent jsonb not null default '{}'::jsonb;
alter table public.scenes add column coverage jsonb not null default '{}'::jsonb;
alter table public.first_frames add column checks jsonb not null default '[]'::jsonb;

comment on column public.shots.intent is
  'contracts.staging.ShotIntent: purpose, what we see, emotional beat, who is on screen or only heard. by = model | rules | person; an agent never replaces a person''s.';
comment on column public.scenes.coverage is
  'contracts.staging.ScenePlan: the scene''s axis, motif and size progression. by = model | rules | person.';
comment on column public.first_frames.checks is
  '[contracts.producer.Check]: advisories on a painted frame (a missing reference sheet; a vision model''s look at it).';
