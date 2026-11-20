-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v26 to schema v27 (Omni Flash 1.2 only, plan/2026-11-19 D8): a shot may
-- be any whole number of seconds from 3 to 15 (Omni Flash 1.2's range). Which of those a production uses is its setting
-- (`productions.settings.take_lengths` / `max_take_s`), checked by the API, not here.
--
-- Safe to re-run. Nothing is backfilled: every shot that exists is 4, 6 or 8 s and still fits.
--
-- HOW TO APPLY: only on a project that already has schema v26 (apply upgrade_v25_to_v26.sql first). SQL Editor → paste
-- this whole file → Run, once. A NEW project runs schema_v27.sql instead (v26 + this file gives the same schema as v27).
-- Nothing is applied to the hosted project until the person says so. Until it is applied, saving a shot of 3, 5, 7, 9 or
-- more seconds fails in the database.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.shots drop constraint if exists shots_duration_s_check;
alter table public.shots add constraint shots_duration_s_check check (duration_s between 3 and 15);
comment on column public.shots.duration_s is
  'Seconds, 3 to 15 (Omni Flash 1.2). The production''s take_lengths / max_take_s say which of these its shots use.';

notify pgrst, 'reload schema';

commit;
