-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v15 to schema v16 (the document reader, plan/2026-11-06f:
-- documents.reading_path / read_from and scenes.read_from / read_confirmed_by / read_confirmed_at).
--
-- documents.reading_path: the stored reading in the documents bucket (null = not read); read_from: 'text' (checked word
-- for word) or 'pages' (read from the page images). scenes.read_from: how the scene's script was read (null = the
-- rules); read_confirmed_by / _at: the person who checked a 'pages' scene's dialogue, cleared when a build rewrites it.
--
-- Safe to re-run: every statement skips what already exists (also on a project whose v14 upgrade already added them).
--
-- HOW TO APPLY: only on a project that already has schema v15. SQL Editor → paste this whole file → Run, once. A NEW project runs
-- schema_v16.sql instead (v15 + this file gives the same schema as v16). Until it is applied, keep READER__ENABLED=false:
-- with the reader on, doc_ingest and structure_build write these columns. Nothing is applied to the hosted project until the
-- person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.documents add column if not exists reading_path text;
alter table public.documents add column if not exists read_from text check (read_from in ('text', 'pages'));
alter table public.scenes add column if not exists read_from text check (read_from in ('text', 'pages'));
alter table public.scenes add column if not exists read_confirmed_by uuid references public.profiles (id) on delete set null;
alter table public.scenes add column if not exists read_confirmed_at timestamptz;
create index if not exists scenes_read_confirmed_by_idx on public.scenes (read_confirmed_by);

commit;
