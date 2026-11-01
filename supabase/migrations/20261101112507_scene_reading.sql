-- Shots planned by a director (plan/2026-11-01d, Phase 1): what a scene is about, before it is cut.
--
--   scenes.reading   contracts.reading.SceneReading  (about, value start -> end, tone, units with turns, subtext,
--                    breath, ending; by = model | rules | person; for_version + basis say what it was written for)
--
-- JSON, optional; a scene with no reading reads as `{}` and is timed exactly as before. No new table and no new
-- policy: the existing read policy covers the column, and the API and the functions write it with the service role.

alter table public.scenes add column reading jsonb not null default '{}'::jsonb;

comment on column public.scenes.reading is
  'contracts.reading.SceneReading: what the scene is about, where the feeling turns, what to hold. by = model | rules | person; a person''s reading is never replaced by the system, a script edit only marks it stale.';
