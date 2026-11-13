-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v23 to schema v24 (take posters, plan/2026-11-13b phase 9): `takes.poster_path`
-- and `image/webp` allowed in the `takes` bucket, so the assembler's `<take>.poster.webp` can be stored.
--
-- Safe to re-run. Nothing is backfilled here: `python scripts/backfill_thumbs.py --apply --posters` makes the missing stills
-- and records them. The API works before and after this file (a take with no `poster_path` simply shows no still).
--
-- HOW TO APPLY: only on a project that already has schema v23 (apply upgrade_v22_to_v23.sql first). SQL Editor → paste this
-- whole file → Run, once. A NEW project runs schema_v24.sql instead (v23 + this file gives the same schema as v24). Nothing
-- is applied to the hosted project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.takes add column if not exists poster_path text;
comment on column public.takes.poster_path is
  'takes bucket, <take>.poster.webp; null until the still exists (the card shows no still without it)';

update storage.buckets
   set allowed_mime_types = array['video/mp4', 'video/quicktime', 'video/webm', 'image/webp']
 where id = 'takes';

notify pgrst, 'reload schema';

commit;
