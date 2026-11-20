-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v27 to schema v28 (long lines in parts, plan/2026-11-20 D9): a scene
-- remembers that Shot Planner Raphael planned it with its long lines in parts (`scenes.line_parts`). Every reader then
-- cuts the scene's lines the same way (`contracts.sceneplan.scene_items`), so the shots' block numbers, which count the
-- parts, stay valid. A scene planned before keeps whole lines (false).
--
-- Safe to re-run. Nothing is backfilled: every scene that exists was planned with whole lines.
--
-- HOW TO APPLY: only on a project that already has schema v27 (apply upgrade_v26_to_v27.sql first). SQL Editor → paste
-- this whole file → Run, once. A NEW project runs schema_v28.sql instead (v27 + this file gives the same schema as v28).
-- Nothing is applied to the hosted project until the person says so. Turn on RAPHAEL_LINE_PARTS only after it is applied.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.scenes add column if not exists line_parts boolean not null default false;
comment on column public.scenes.line_parts is
  'True when the shots were planned with long lines in parts (plan/2026-11-20): block numbers count the parts.';

notify pgrst, 'reload schema';

commit;
