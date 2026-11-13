-- Take posters (plan/2026-11-13b phase 9): `takes.poster_path` and `image/webp` in the `takes` bucket, which refused the
-- assembler's `<take>.poster.webp`. Schema v24 (Database/schema_v24.sql, upgrade_v23_to_v24.sql).
alter table public.takes add column if not exists poster_path text;
comment on column public.takes.poster_path is
  'takes bucket, <take>.poster.webp; null until the still exists (the card shows no still without it)';

update storage.buckets
   set allowed_mime_types = array['video/mp4', 'video/quicktime', 'video/webm', 'image/webp']
 where id = 'takes';
