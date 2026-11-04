-- Shots planned by a director (plan/2026-11-01d, Phase 4): where everyone is, block by block.
--
--   scenes.staging   contracts.stagemap.SceneStaging  (zones: 2-6 named spots; marks: from this block on, this person
--                    is in this zone, facing this way, on this side of the frame; by = model | person; for_version +
--                    basis say what it was written for)
--
-- JSON, optional; a scene with no map reads as `{}` and nothing about places is checked. No new table and no new
-- policy: the existing read policy covers the column, and the API and the functions write it with the service role.

alter table public.scenes add column staging jsonb not null default '{}'::jsonb;

comment on column public.scenes.staging is
  'contracts.stagemap.SceneStaging: the scene''s spots and where each person is, block by block. Checked in code for teleports, crossed lines and eyelines. by = model | person; a person''s map is never replaced.';
