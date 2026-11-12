-- ═══════════════════════════════════════════════════════════════════════════════════════════
-- Hiru AI Studio — upgrade a project from schema v21 to schema v22 (house rules and implied things, plan/2026-11-12
-- §3.2): a canon version may now come from `inferred`, a thing the script implies but does not name (the phone a voice
-- message plays from). The breakdown writes it; a person can rename, change or delete it like any other entry.
--
-- Safe to re-run: the check is dropped and added again with the same name. Nothing is backfilled.
--
-- HOW TO APPLY: only on a project that already has schema v21. SQL Editor → paste this whole file → Run, once. A NEW
-- project runs schema_v22.sql instead (v21 + this file gives the same schema as v22). Nothing is applied to the hosted
-- project until the person says so.
-- ═══════════════════════════════════════════════════════════════════════════════════════════
begin;

alter table public.canon_versions drop constraint if exists canon_versions_source_check;
alter table public.canon_versions
  add constraint canon_versions_source_check check (source in ('extract', 'user', 'inferred'));
comment on column public.canon_versions.source is
  'extract: read from a document; user: a person''s edit; inferred: implied by the script, not named in it (plan/2026-11-12)';

notify pgrst, 'reload schema';

commit;
